// Packizard Builder - native naps_pkg_layout.dat binary writer.
// No LibProsperoPkg NAPS builder/serializer is called from this path.  The shared model types are used
// only as DTOs so existing package code can inspect the result.
#nullable enable
using System;
using System.Buffers.Binary;

namespace LibProsperoPkg.PKG;

public static class PackizardNativeNapsWriter
{
    private const int HeaderSize = 16;
    private const int OuterDigestStride = 8;
    private const int ShuffleStride = 8;
    private const int FidxStride = 6;
    private const int U2cStride = 10;
    private const int CblockStride = 9;

    public static byte[] Serialize(NapsLayoutDocument document, int alignment = 16)
    {
        ArgumentNullException.ThrowIfNull(document);
        PackizardNativeNapsValidator.ValidateDocument(document);

        NapsLayoutCounts c = document.Counts;
        long content = checked(
            HeaderSize
            + (long)c.NumOuterBlocks * OuterDigestStride
            + (long)c.NumShufflePatterns * ShuffleStride
            + (long)document.FileOffsets.Count * FidxStride
            + (long)document.CblockInfoOffsetByUblock.Count * U2cStride
            + (long)c.NumCblockInfo * CblockStride);
        long total = alignment > 1
            ? checked((content + alignment - 1) / alignment * alignment)
            : content;
        if (total > int.MaxValue)
            throw new NotSupportedException(
                $"Packizard NAPS descriptor is {total:N0} bytes; the current in-memory writer is limited to {int.MaxValue:N0}.");

        var blob = new byte[(int)total];
        Span<byte> dst = blob;
        int pos = 0;

        WriteHeader(dst.Slice(pos, HeaderSize), c);
        pos += HeaderSize;

        foreach (byte[] digest in document.OuterBlockDigests)
        {
            digest.CopyTo(dst.Slice(pos, OuterDigestStride));
            pos += OuterDigestStride;
        }
        foreach (byte[] shuffle in document.ShufflePatterns)
        {
            shuffle.CopyTo(dst.Slice(pos, ShuffleStride));
            pos += ShuffleStride;
        }
        foreach (NapsFileOffsetEntry entry in document.FileOffsets)
        {
            WriteFidx(dst.Slice(pos, FidxStride), entry);
            pos += FidxStride;
        }
        foreach (NapsU2cEntry entry in document.CblockInfoOffsetByUblock)
        {
            WriteU2c(dst.Slice(pos, U2cStride), entry);
            pos += U2cStride;
        }
        foreach (NapsCblockInfoEntry entry in document.CblockInfos)
        {
            WriteCblock(dst.Slice(pos, CblockStride), entry);
            pos += CblockStride;
        }

        if (pos != content)
            throw new InvalidOperationException(
                $"Packizard NAPS writer position mismatch: {pos:N0}/{content:N0}.");
        // byte[] is zero-initialized; any alignment tail is intentionally zero padding.
        return blob;
    }

    private static void WriteHeader(Span<byte> dst, NapsLayoutCounts c)
    {
        ulong word0 =
              (ulong)(uint)(c.NumFiles - 1)
            | ((ulong)c.CompressionType << 24)
            | ((ulong)(uint)(c.NumKeys - 1) << 26)
            | ((ulong)(uint)c.NumShufflePatterns << 28)
            | ((ulong)(uint)c.NumUBlocks << 32);
        ulong word1 =
              (ulong)(uint)c.NumOuterBlocks
            | ((ulong)(uint)(c.NumCblockInfo - 2) << 24);
        BinaryPrimitives.WriteUInt64LittleEndian(dst[..8], word0);
        BinaryPrimitives.WriteUInt64LittleEndian(dst[8..16], word1);
    }

    private static void WriteFidx(Span<byte> dst, NapsFileOffsetEntry entry)
    {
        ulong value = entry.UncompressedOffsetStart;
        dst[0] = (byte)value;
        dst[1] = (byte)(value >> 8);
        dst[2] = (byte)(value >> 16);
        dst[3] = (byte)(value >> 24);
        dst[4] = (byte)(value >> 32);
        dst[5] = entry.Type;
    }

    private static void WriteU2c(Span<byte> dst, NapsU2cEntry entry)
    {
        uint b = entry.InfoOffset9BBase;
        dst[0] = (byte)b;
        dst[1] = (byte)(b >> 8);
        dst[2] = (byte)(b >> 16);
        for (int i = 0; i < 7; i++)
            dst[3 + i] = entry.DeltaFromBase[i];
    }

    private static void WriteCblock(Span<byte> dst, NapsCblockInfoEntry e)
    {
        ulong lo;
        byte hi;
        if (!e.IsRunBase)
        {
            lo = e.CoffsetStartMod256K;
            lo |= (ulong)e.UoffsetStart << 19;
            lo |= (ulong)e.ClenEvenMinus1 << 37;
            lo |= (ulong)e.Even << 54;
            lo |= (ulong)e.Odd << 55;
            lo |= (ulong)e.KdePredictor << 56;
            lo |= (ulong)e.ShuffleIdx << 59;
            hi = 0;
        }
        else
        {
            lo = e.CoffsetEndMod256K;
            lo |= 1UL << 18;
            lo |= (ulong)e.TweakIdxStart << 19;
            lo |= (ulong)e.KeyTableIdx << 47;
            lo |= (ulong)(e.CoffsetStart256K & 0x7FFF) << 49;
            hi = checked((byte)(e.CoffsetStart256K >> 15));
        }

        for (int i = 0; i < 8; i++)
            dst[i] = (byte)(lo >> (8 * i));
        dst[8] = hi;
    }
}
