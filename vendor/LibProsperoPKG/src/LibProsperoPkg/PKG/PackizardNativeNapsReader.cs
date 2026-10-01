// Packizard Builder - native naps_pkg_layout.dat reader.
// Parses exactly the layout emitted by PackizardNativeNapsWriter.  In particular, Packizard's authored
// fidx contract is explicit: header.NumFiles logical entries plus one six-byte trailer.  We do not infer
// fidx count from aligned blob length, because final zero padding can accidentally look like extra fidx rows.
#nullable enable
using System;
using System.Buffers.Binary;
using System.Collections.Generic;

namespace LibProsperoPkg.PKG;

public static class PackizardNativeNapsReader
{
    private const int HeaderSize = 16;
    private const int OuterDigestStride = 8;
    private const int ShuffleStride = 8;
    private const int FidxStride = 6;
    private const int U2cStride = 10;
    private const int CblockStride = 9;

    public static NapsLayoutDocument Parse(ReadOnlySpan<byte> blob)
    {
        if (blob.Length < HeaderSize)
            throw new InvalidOperationException(
                $"Packizard NAPS blob is only {blob.Length} bytes; header needs {HeaderSize}.");

        NapsLayoutCounts counts = ReadHeader(blob[..HeaderSize]);
        int fidxCount = checked(counts.NumFiles + 1); // Packizard contract: authored rows + trailer
        int u2cCount = checked((counts.NumUBlocks + 8) >> 3);
        long contentLength = checked(
            HeaderSize
            + (long)counts.NumOuterBlocks * OuterDigestStride
            + (long)counts.NumShufflePatterns * ShuffleStride
            + (long)fidxCount * FidxStride
            + (long)u2cCount * U2cStride
            + (long)counts.NumCblockInfo * CblockStride);
        if (contentLength > blob.Length)
            throw new InvalidOperationException(
                $"Packizard NAPS sections need {contentLength:N0} bytes, blob has {blob.Length:N0}.");
        if (contentLength > int.MaxValue)
            throw new NotSupportedException(
                $"Packizard NAPS reader cannot index {contentLength:N0} bytes in one span.");

        // Writer alignment is zero padding only.  Reject any nonzero tail so a shifted section map cannot
        // silently pass round-trip validation.
        for (int i = checked((int)contentLength); i < blob.Length; i++)
            if (blob[i] != 0)
                throw new InvalidOperationException(
                    $"Packizard NAPS has nonzero alignment/trailing byte at 0x{i:X}.");

        int pos = HeaderSize;
        var outer = new byte[counts.NumOuterBlocks][];
        for (int i = 0; i < outer.Length; i++)
        {
            outer[i] = blob.Slice(pos, OuterDigestStride).ToArray();
            pos += OuterDigestStride;
        }

        var shuffle = new byte[counts.NumShufflePatterns][];
        for (int i = 0; i < shuffle.Length; i++)
        {
            shuffle[i] = blob.Slice(pos, ShuffleStride).ToArray();
            pos += ShuffleStride;
        }

        var fidx = new NapsFileOffsetEntry[fidxCount];
        for (int i = 0; i < fidx.Length; i++)
        {
            fidx[i] = ReadFidx(blob.Slice(pos, FidxStride));
            pos += FidxStride;
        }

        var u2c = new NapsU2cEntry[u2cCount];
        for (int i = 0; i < u2c.Length; i++)
        {
            u2c[i] = ReadU2c(blob.Slice(pos, U2cStride));
            pos += U2cStride;
        }

        var cblocks = new NapsCblockInfoEntry[counts.NumCblockInfo];
        for (int i = 0; i < cblocks.Length; i++)
        {
            cblocks[i] = ReadCblock(blob.Slice(pos, CblockStride));
            pos += CblockStride;
        }

        if (pos != contentLength)
            throw new InvalidOperationException(
                $"Packizard NAPS reader position mismatch: {pos:N0}/{contentLength:N0}.");

        var document = new NapsLayoutDocument
        {
            Counts = counts,
            Map = default,
            OuterBlockDigests = outer,
            ShufflePatterns = shuffle,
            FileOffsets = fidx,
            CblockInfoOffsetByUblock = u2c,
            CblockInfos = cblocks,
        };
        PackizardNativeNapsValidator.ValidateDocument(document);
        return document;
    }

    private static NapsLayoutCounts ReadHeader(ReadOnlySpan<byte> src)
    {
        ulong w0 = BinaryPrimitives.ReadUInt64LittleEndian(src[..8]);
        ulong w1 = BinaryPrimitives.ReadUInt64LittleEndian(src[8..16]);
        int numFiles = checked((int)(w0 & 0xFFFFFF) + 1);
        byte compression = (byte)((w0 >> 24) & 0x3);
        int numKeys = checked((int)((w0 >> 26) & 0x3) + 1);
        int shuffles = checked((int)((w0 >> 28) & 0xF));
        int ublocks = checked((int)((w0 >> 32) & 0xFFFFFF));
        int outer = checked((int)(w1 & 0xFFFFFF));
        int cblocks = checked((int)((w1 >> 24) & 0xFFFFFF) + 2);
        return new NapsLayoutCounts(numFiles, compression, numKeys, shuffles, ublocks, outer, cblocks);
    }

    private static NapsFileOffsetEntry ReadFidx(ReadOnlySpan<byte> src)
    {
        ulong value = (ulong)src[0]
            | ((ulong)src[1] << 8)
            | ((ulong)src[2] << 16)
            | ((ulong)src[3] << 24)
            | ((ulong)src[4] << 32);
        return new NapsFileOffsetEntry(src[5], value);
    }

    private static NapsU2cEntry ReadU2c(ReadOnlySpan<byte> src)
    {
        uint b = (uint)(src[0] | (src[1] << 8) | (src[2] << 16));
        return new NapsU2cEntry(b, src.Slice(3, 7).ToArray());
    }

    private static NapsCblockInfoEntry ReadCblock(ReadOnlySpan<byte> src)
    {
        ulong lo = BinaryPrimitives.ReadUInt64LittleEndian(src[..8]);
        byte hi = src[8];
        bool run = ((lo >> 18) & 1) != 0;
        var raw = src.ToArray();
        if (!run)
        {
            return new NapsCblockInfoEntry
            {
                Raw = raw,
                IsRunBase = false,
                CoffsetStartMod256K = (uint)(lo & 0x3FFFF),
                UoffsetStart = (uint)((lo >> 19) & 0x3FFFF),
                ClenEvenMinus1 = (uint)((lo >> 37) & 0x1FFFF),
                Even = (byte)((lo >> 54) & 1),
                Odd = (byte)((lo >> 55) & 1),
                KdePredictor = (byte)((lo >> 56) & 7),
                ShuffleIdx = (byte)((lo >> 59) & 0xF),
            };
        }
        return new NapsCblockInfoEntry
        {
            Raw = raw,
            IsRunBase = true,
            CoffsetEndMod256K = (uint)(lo & 0x3FFFF),
            TweakIdxStart = (uint)((lo >> 19) & 0x0FFFFFFF),
            KeyTableIdx = (byte)((lo >> 47) & 3),
            CoffsetStart256K = (uint)(((lo >> 49) & 0x7FFF) | ((ulong)hi << 15)),
        };
    }
}
