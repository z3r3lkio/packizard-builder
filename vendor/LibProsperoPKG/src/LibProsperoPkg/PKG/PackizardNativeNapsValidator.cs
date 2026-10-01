// Packizard Builder - native NAPS structural validation.
#nullable enable
using System;

namespace LibProsperoPkg.PKG;

public static class PackizardNativeNapsValidator
{
    public static void ValidateDocument(NapsLayoutDocument document)
    {
        ArgumentNullException.ThrowIfNull(document);
        NapsLayoutCounts c = document.Counts;

        Require(c.NumFiles is >= 1 and <= 0x1000000,
            $"NumFiles {c.NumFiles:N0} is outside the 24-bit minus-one field.");
        Require(c.CompressionType <= 3,
            $"CompressionType {c.CompressionType} exceeds 2 bits.");
        Require(c.NumKeys is >= 1 and <= 4,
            $"NumKeys {c.NumKeys} is outside the 2-bit minus-one field.");
        Require(c.NumShufflePatterns is >= 0 and <= 15,
            $"NumShufflePatterns {c.NumShufflePatterns} exceeds 4 bits.");
        Require(c.NumUBlocks is >= 0 and <= 0xFFFFFF,
            $"NumUBlocks {c.NumUBlocks:N0} exceeds 24 bits.");
        Require(c.NumOuterBlocks is >= 0 and <= 0xFFFFFF,
            $"NumOuterBlocks {c.NumOuterBlocks:N0} exceeds 24 bits.");
        Require(c.NumCblockInfo is >= 2 and <= 0x1000001,
            $"NumCblockInfo {c.NumCblockInfo:N0} is outside the 24-bit minus-two field.");

        Require(document.OuterBlockDigests.Count == c.NumOuterBlocks,
            $"OuterBlockDigests count {document.OuterBlockDigests.Count} != {c.NumOuterBlocks}.");
        Require(document.ShufflePatterns.Count == c.NumShufflePatterns,
            $"ShufflePatterns count {document.ShufflePatterns.Count} != {c.NumShufflePatterns}.");
        // Packizard writer contract: NumFiles authored fidx rows plus the fixed six-byte trailer.
        Require(document.FileOffsets.Count == checked(c.NumFiles + 1),
            $"FileOffsets count {document.FileOffsets.Count} != Packizard contract NumFiles+1 ({c.NumFiles + 1}).");
        int expectedU2c = (c.NumUBlocks + 8) >> 3;
        Require(document.CblockInfoOffsetByUblock.Count == expectedU2c,
            $"u2c count {document.CblockInfoOffsetByUblock.Count} != {expectedU2c}.");
        Require(document.CblockInfos.Count == c.NumCblockInfo,
            $"CblockInfo count {document.CblockInfos.Count} != {c.NumCblockInfo}.");

        for (int i = 0; i < document.OuterBlockDigests.Count; i++)
            Require(document.OuterBlockDigests[i].Length == 8,
                $"Outer digest {i} is {document.OuterBlockDigests[i].Length} bytes, expected 8.");
        for (int i = 0; i < document.ShufflePatterns.Count; i++)
            Require(document.ShufflePatterns[i].Length == 8,
                $"Shuffle pattern {i} is {document.ShufflePatterns[i].Length} bytes, expected 8.");

        ulong previousFidx = 0;
        for (int i = 0; i < document.FileOffsets.Count; i++)
        {
            NapsFileOffsetEntry f = document.FileOffsets[i];
            Require(f.UncompressedOffsetStart <= 0xFFFFFFFFFFUL,
                $"fidx[{i}] offset 0x{f.UncompressedOffsetStart:X} exceeds 40 bits.");
            // The final fixed trailer is intentionally not a logical offset; only validate monotonicity
            // across the authored fidx records before it.
            if (i + 1 < document.FileOffsets.Count)
            {
                Require(f.UncompressedOffsetStart >= previousFidx,
                    $"fidx[{i}] moved backwards: 0x{f.UncompressedOffsetStart:X} < 0x{previousFidx:X}.");
                previousFidx = f.UncompressedOffsetStart;
            }
        }

        uint previousBase = 0;
        for (int i = 0; i < document.CblockInfoOffsetByUblock.Count; i++)
        {
            NapsU2cEntry u = document.CblockInfoOffsetByUblock[i];
            Require(u.InfoOffset9BBase <= 0xFFFFFF,
                $"u2c[{i}] base {u.InfoOffset9BBase} exceeds 24 bits.");
            byte[] deltas = u.DeltaFromBase
                ?? throw new InvalidOperationException(
                    $"Packizard native NAPS validation failed: u2c[{i}] delta array is null.");
            Require(deltas.Length == 7,
                $"u2c[{i}] must contain exactly seven delta bytes, got {deltas.Length}.");
            Require(u.InfoOffset9BBase < c.NumCblockInfo,
                $"u2c[{i}] base {u.InfoOffset9BBase} is outside CblockInfo count {c.NumCblockInfo}.");
            for (int j = 0; j < 7; j++)
            {
                uint target = u.InfoOffset9BBase + deltas[j];
                Require(target < c.NumCblockInfo,
                    $"u2c[{i}] delta[{j}] resolves to CblockInfo {target}, outside {c.NumCblockInfo}.");
            }
            if (i > 0)
                Require(u.InfoOffset9BBase >= previousBase,
                    $"u2c base moved backwards at group {i}: {u.InfoOffset9BBase} < {previousBase}.");
            previousBase = u.InfoOffset9BBase;
        }

        for (int i = 0; i < document.CblockInfos.Count; i++)
            ValidateCblock(i, document.CblockInfos[i]);
    }

    private static void ValidateCblock(int index, NapsCblockInfoEntry e)
    {
        if (!e.IsRunBase)
        {
            Require(e.CoffsetStartMod256K <= 0x3FFFF,
                $"CblockInfo[{index}] coffsetStartMod256K exceeds 18 bits.");
            Require(e.UoffsetStart <= 0x3FFFF,
                $"CblockInfo[{index}] uoffsetStart exceeds 18 bits.");
            Require(e.ClenEvenMinus1 <= 0x1FFFF,
                $"CblockInfo[{index}] clenEvenMinus1 exceeds 17 bits.");
            Require(e.Even <= 1 && e.Odd <= 1,
                $"CblockInfo[{index}] even/odd flags are not one bit.");
            Require(e.KdePredictor <= 7,
                $"CblockInfo[{index}] KDE predictor exceeds 3 bits.");
            Require(e.ShuffleIdx <= 15,
                $"CblockInfo[{index}] shuffle index exceeds 4 bits.");
        }
        else
        {
            Require(e.CoffsetEndMod256K <= 0x3FFFF,
                $"CblockInfo[{index}] coffsetEndMod256K exceeds 18 bits.");
            Require(e.TweakIdxStart <= 0x0FFFFFFF,
                $"CblockInfo[{index}] tweak index exceeds 28 bits.");
            Require(e.KeyTableIdx <= 3,
                $"CblockInfo[{index}] key table index exceeds 2 bits.");
            // The modeled RUN record has 15 low bits in word0 plus byte[8] = 23 physically serialized bits.
            // Do not advertise the nominal 24-bit label and then silently drop bit 23.
            Require(e.CoffsetStart256K <= 0x7FFFFF,
                $"CblockInfo[{index}] coffsetStart256K 0x{e.CoffsetStart256K:X} exceeds the 23 physically serialized bits.");
        }
    }

    private static void Require(bool condition, string message)
    {
        if (!condition)
            throw new InvalidOperationException("Packizard native NAPS validation failed: " + message);
    }
}
