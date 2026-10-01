using System;
using System.Collections.Generic;
using System.IO;

namespace LibProsperoPkg.PFS;

/// <summary>Owns build intermediates until explicitly handed to the next stage.</summary>
internal sealed class ProsperoBuildTempFiles : IDisposable
{
    private readonly HashSet<string> paths = new(StringComparer.Ordinal);

    public string Create()
    {
        string path = Path.Combine(Path.GetTempPath(), $"libprospero-{Guid.NewGuid():N}.tmp");
        using (new FileStream(path, FileMode.CreateNew, FileAccess.Write, FileShare.None)) { }
        paths.Add(path);
        return path;
    }

    public void Own(string? path)
    {
        if (!string.IsNullOrEmpty(path)) paths.Add(path);
    }

    public void Release(string? path)
    {
        if (!string.IsNullOrEmpty(path)) paths.Remove(path);
    }

    public void Dispose()
    {
        foreach (string path in paths)
        {
            try { File.Delete(path); }
            catch (IOException) { }
            catch (UnauthorizedAccessException) { }
        }
        paths.Clear();
    }
}
