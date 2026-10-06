#!/usr/bin/env python3
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1] / "ampr_emu"
CONFIG = ROOT / "include" / "ampr_emu_config.h"
PACK = ROOT / "src" / "ampr_emu_pack.cpp"
HOOK = ROOT / "src" / "ampr_libkernel_hook.cpp"
INDEX = ROOT / "src" / "ampr_emu_index.cpp"
EXPORTS = ROOT / "src" / "sceampr_exports.cpp"


def replace_once(path: Path, old: str, new: str) -> None:
    text = path.read_text(encoding="utf-8")
    count = text.count(old)
    if count != 1:
        raise RuntimeError(
            f"{path}: expected exactly one anchor, found {count}: {old[:80]!r}"
        )
    path.write_text(text.replace(old, new, 1), encoding="utf-8", newline="\n")


config_anchor = """#ifndef AMPR_EMU_PACK_TELEMETRY
// Collect pack counters and worker/AIO latency samples used only by diagnostic
"""
config_insert = """#ifndef AMPR_EMU_PACK_AIO_PREAD_FALLBACK
// Retry failed or short backing-pack AIO reads synchronously with pread().
// This is a backend-compatibility safety net, not a title-specific workaround.
#define AMPR_EMU_PACK_AIO_PREAD_FALLBACK 1
#endif

#ifndef AMPR_EMU_PACK_IO_COMPAT_DIAGNOSTICS
// Low-volume, always-on diagnostics for backing-pack compatibility testing.
#define AMPR_EMU_PACK_IO_COMPAT_DIAGNOSTICS 1
#endif

#ifndef AMPR_EMU_PACK_TELEMETRY
// Collect pack counters and worker/AIO latency samples used only by diagnostic
"""
replace_once(CONFIG, config_anchor, config_insert)

helper_anchor = """static bool bytes_equal(const void* a, const void* b, size_t size) {
    return std::memcmp(a, b, size) == 0;
}
"""
helper_insert = """#if AMPR_EMU_PACK_AIO_PREAD_FALLBACK
static std::atomic<uint64_t> g_backingFallbackAttempts{0};
static std::atomic<uint64_t> g_backingFallbackSuccesses{0};
static std::atomic<uint64_t> g_backingFallbackFailures{0};

static bool retry_backing_request_with_pread(
    const SceKernelAioRWRequest& request,
    SceKernelAioResult& result,
    int priorError) {
    const int64_t priorReturnValue = result.returnValue;
    const uint64_t attempt =
        g_backingFallbackAttempts.fetch_add(1, std::memory_order_relaxed) + 1;

#if AMPR_EMU_PACK_IO_COMPAT_DIAGNOSTICS
    // Keep successful diagnostic output bounded while always logging failures.
    if (attempt <= 64) {
        AMPR_KLOGF(
            "[AMPR_IO] fallback.enter seq=%llu fd=%d off=0x%llx req=0x%llx aio_ret=%lld prior=0x%x",
            (unsigned long long)attempt,
            request.fd,
            (unsigned long long)request.offset,
            (unsigned long long)request.nbyte,
            (long long)priorReturnValue,
            priorError);
    }
#endif

    if (request.nbyte == 0) {
        result.returnValue = 0;
        g_backingFallbackSuccesses.fetch_add(1, std::memory_order_relaxed);
        return true;
    }
    if (request.fd < 0 || !request.buf || request.offset < 0) {
        g_backingFallbackFailures.fetch_add(1, std::memory_order_relaxed);
        AMPR_KLOGF(
            "[AMPR_IO] fallback.reject seq=%llu fd=%d off=0x%llx req=0x%llx aio_ret=%lld prior=0x%x",
            (unsigned long long)attempt,
            request.fd,
            (unsigned long long)request.offset,
            (unsigned long long)request.nbyte,
            (long long)priorReturnValue,
            priorError);
        return false;
    }

    errno = 0;
    const bool ok = pread_exact(
        request.fd,
        request.buf,
        request.nbyte,
        static_cast<uint64_t>(request.offset));
    const int fallbackErrno = errno;

    if (ok) {
        const uint64_t successes =
            g_backingFallbackSuccesses.fetch_add(1, std::memory_order_relaxed) + 1;
        result.returnValue = static_cast<int64_t>(request.nbyte);
#if AMPR_EMU_PACK_IO_COMPAT_DIAGNOSTICS
        if (attempt <= 64) {
            AMPR_KLOGF(
                "[AMPR_IO] fallback.pread.ok seq=%llu ok=%llu fd=%d off=0x%llx req=0x%llx aio_ret=%lld prior=0x%x",
                (unsigned long long)attempt,
                (unsigned long long)successes,
                request.fd,
                (unsigned long long)request.offset,
                (unsigned long long)request.nbyte,
                (long long)priorReturnValue,
                priorError);
        }
#endif
        return true;
    }

    const uint64_t failures =
        g_backingFallbackFailures.fetch_add(1, std::memory_order_relaxed) + 1;
    AMPR_KLOGF(
        "[AMPR_IO] fallback.pread.fail seq=%llu fail=%llu fd=%d off=0x%llx req=0x%llx aio_ret=%lld prior=0x%x errno=%d",
        (unsigned long long)attempt,
        (unsigned long long)failures,
        request.fd,
        (unsigned long long)request.offset,
        (unsigned long long)request.nbyte,
        (long long)priorReturnValue,
        priorError,
        fallbackErrno);
    return false;
}
#endif

static bool bytes_equal(const void* a, const void* b, size_t size) {
    return std::memcmp(a, b, size) == 0;
}
"""
replace_once(PACK, helper_anchor, helper_insert)

mandatory_anchor = """static int finish_mandatory_page_group(ReadPipelineContext& pipeline) {
    PackState& state = pack_state();
    const int completionError = pipeline.nativeIoError;
    int groupError = completionError;
    release_mandatory_fds(pipeline);
"""
mandatory_insert = """static int finish_mandatory_page_group(ReadPipelineContext& pipeline) {
    PackState& state = pack_state();
    int completionError = pipeline.nativeIoError;
    int groupError = completionError;

#if AMPR_EMU_PACK_AIO_PREAD_FALLBACK
    if (completionError != SCE_KERNEL_ERROR_ECANCELED) {
        const int groupPriorError = completionError;
        bool fallbackFailed = false;

        for (size_t requestIndex = 0;
             requestIndex < pipeline.mandatoryRequestCount;
             ++requestIndex) {
            const SceKernelAioRWRequest& request =
                pipeline.mandatoryRequests[requestIndex];
            SceKernelAioResult& result =
                pipeline.mandatoryResults[requestIndex];

            int requestError = groupPriorError;
            if (requestError == 0 &&
                result.returnValue != static_cast<int64_t>(request.nbyte)) {
                requestError = result.returnValue < 0
                    ? static_cast<int>(result.returnValue)
                    : SCE_KERNEL_ERROR_EIO;
            }

            if (requestError != 0 &&
                !retry_backing_request_with_pread(
                    request, result, requestError)) {
                result.returnValue = requestError;
                fallbackFailed = true;
            }
        }

        if (!fallbackFailed) {
            completionError = 0;
            groupError = 0;
        }
    }
#endif

    release_mandatory_fds(pipeline);
"""
replace_once(PACK, mandatory_anchor, mandatory_insert)

window_anchor = """    if (error == 0 &&
        pipeline.nativeResult.returnValue != static_cast<int64_t>(range.length)) {
        error = pipeline.nativeResult.returnValue < 0
                    ? static_cast<int>(pipeline.nativeResult.returnValue)
                    : SCE_KERNEL_ERROR_EIO;
    }
    if (pipeline.packFd >= 0) {
"""
window_insert = """    if (error == 0 &&
        pipeline.nativeResult.returnValue != static_cast<int64_t>(range.length)) {
        error = pipeline.nativeResult.returnValue < 0
                    ? static_cast<int>(pipeline.nativeResult.returnValue)
                    : SCE_KERNEL_ERROR_EIO;
    }

#if AMPR_EMU_PACK_AIO_PREAD_FALLBACK
    if (error != 0 && error != SCE_KERNEL_ERROR_ECANCELED &&
        pipeline.packFd >= 0) {
        const int priorError = error;
        if (retry_backing_request_with_pread(
                pipeline.nativeRequest,
                pipeline.nativeResult,
                priorError)) {
            error = 0;
        }
    }
#endif

    if (pipeline.packFd >= 0) {
"""
replace_once(PACK, window_anchor, window_insert)

identity_anchor = """    if (debugOut(AMPR_EMU_DEBUG_LOG_KERNEL_OUT_CHANNEL, line) < 0) {
        // Permit a later explicit install attempt to retry a failed system-log
"""
identity_insert = """    if (debugOut(AMPR_EMU_DEBUG_LOG_KERNEL_OUT_CHANNEL, line) < 0) {
        // Permit a later explicit install attempt to retry a failed system-log
"""
# Add an unmistakable runtime marker immediately after the normal module identity
# has been emitted successfully.
marker_anchor = """    if (debugOut(AMPR_EMU_DEBUG_LOG_KERNEL_OUT_CHANNEL, line) < 0) {
        // Permit a later explicit install attempt to retry a failed system-log
        // write without ever involving the file logger.
        g_moduleIdentityLogged.store(0, std::memory_order_release);
    }
}
"""
marker_insert = """    if (debugOut(AMPR_EMU_DEBUG_LOG_KERNEL_OUT_CHANNEL, line) < 0) {
        // Permit a later explicit install attempt to retry a failed system-log
        // write without ever involving the file logger.
        g_moduleIdentityLogged.store(0, std::memory_order_release);
        return;
    }
#if AMPR_EMU_PACK_IO_COMPAT_DIAGNOSTICS
    debugOut(AMPR_EMU_DEBUG_LOG_KERNEL_OUT_CHANNEL,
             "[AMPR_IO] backing-io-debug=1 aio-pread-fallback=1\\n");
#endif
}
"""
replace_once(HOOK, marker_anchor, marker_insert)


# Broad, bounded filesystem diagnostics. These capture all major hypotheses in
# one runtime: path/open resolution, stat/fstat metadata, seek semantics,
# synchronous read semantics, and the physical backing-pack open/stat details.
index_open_anchor = """extern "C" int posix_open_emul(const char* path, int flags, ...) {
    SceKernelMode mode = 0;
"""
index_open_insert = """extern "C" int posix_open_emul(const char* path, int flags, ...) {
    static std::atomic<uint64_t> diagOpenSeq{0};
    SceKernelMode mode = 0;
"""
replace_once(INDEX, index_open_anchor, index_open_insert)

index_open_return_anchor = """    const int result = posix_open_impl(
        path, flags, mode, &expectedIndexMiss);
    return expectedIndexMiss
        ? result
        : ampr_klog_io_hook_path_result("open", path, result);
}
"""
index_open_return_insert = """    const int result = posix_open_impl(
        path, flags, mode, &expectedIndexMiss);
#if AMPR_EMU_PACK_IO_COMPAT_DIAGNOSTICS
    const uint64_t seq = diagOpenSeq.fetch_add(1, std::memory_order_relaxed) + 1;
    if (seq <= 192 || result < 0) {
        AMPR_KLOGF(
            "[AMPR_FS] open seq=%llu path=%s flags=0x%x mode=0%o rc=%d index_miss=%u errno=%d",
            (unsigned long long)seq,
            ampr_log_path_arg(path),
            flags,
            (unsigned)mode,
            result,
            expectedIndexMiss ? 1u : 0u,
            errno);
    }
#endif
    return expectedIndexMiss
        ? result
        : ampr_klog_io_hook_path_result("open", path, result);
}
"""
replace_once(INDEX, index_open_return_anchor, index_open_return_insert)

index_stat_anchor = """extern "C" int posix_stat_emul(const char* path, struct stat* sb) {
    bool expectedIndexMiss = false;
    const int result = posix_stat_impl(path, sb, &expectedIndexMiss);
    return expectedIndexMiss
        ? result
        : ampr_klog_io_hook_path_result("stat", path, result);
}
"""
index_stat_insert = """extern "C" int posix_stat_emul(const char* path, struct stat* sb) {
    static std::atomic<uint64_t> diagStatSeq{0};
    bool expectedIndexMiss = false;
    const int result = posix_stat_impl(path, sb, &expectedIndexMiss);
#if AMPR_EMU_PACK_IO_COMPAT_DIAGNOSTICS
    const uint64_t seq = diagStatSeq.fetch_add(1, std::memory_order_relaxed) + 1;
    if (seq <= 192 || result < 0) {
        AMPR_KLOGF(
            "[AMPR_FS] stat seq=%llu path=%s rc=%d size=%lld mode=0%o index_miss=%u errno=%d",
            (unsigned long long)seq,
            ampr_log_path_arg(path),
            result,
            (long long)((result == 0 && sb) ? sb->st_size : -1),
            (unsigned)((result == 0 && sb) ? sb->st_mode : 0),
            expectedIndexMiss ? 1u : 0u,
            errno);
    }
#endif
    return expectedIndexMiss
        ? result
        : ampr_klog_io_hook_path_result("stat", path, result);
}
"""
replace_once(INDEX, index_stat_anchor, index_stat_insert)

pack_fstat_anchor = """extern "C" int posix_fstat_emul(int fd, struct stat* stat) {
    bool handled = false;
    const int rc = ampr_pack_try_fstat_fd(fd, stat, &handled);
    if (handled) {
        return ampr_klog_io_hook_result("fstat", posix_result_from_pack(rc));
    }
    KernelFstatFn fn = real_fstat();
    return ampr_klog_io_hook_result(
        "fstat", fn ? fn(fd, stat) : posix_missing_original<int>());
}
"""
pack_fstat_insert = """extern "C" int posix_fstat_emul(int fd, struct stat* stat) {
    static std::atomic<uint64_t> diagFstatSeq{0};
    bool handled = false;
    const int packRc = ampr_pack_try_fstat_fd(fd, stat, &handled);
    int result = 0;
    if (handled) {
        result = posix_result_from_pack(packRc);
    } else {
        KernelFstatFn fn = real_fstat();
        result = fn ? fn(fd, stat) : posix_missing_original<int>();
    }
#if AMPR_EMU_PACK_IO_COMPAT_DIAGNOSTICS
    const uint64_t seq = diagFstatSeq.fetch_add(1, std::memory_order_relaxed) + 1;
    if (seq <= 192 || result < 0) {
        AMPR_KLOGF(
            "[AMPR_FS] fstat seq=%llu fd=%d handled=%u rc=%d size=%lld mode=0%o errno=%d",
            (unsigned long long)seq, fd, handled ? 1u : 0u, result,
            (long long)((result == 0 && stat) ? stat->st_size : -1),
            (unsigned)((result == 0 && stat) ? stat->st_mode : 0),
            errno);
    }
#endif
    return ampr_klog_io_hook_result("fstat", result);
}
"""
replace_once(PACK, pack_fstat_anchor, pack_fstat_insert)

pack_lseek_anchor = """extern "C" off_t posix_lseek_emul(int fd, off_t offset, int whence) {
    bool handled = false;
    const off_t rc = ampr_pack_try_lseek_fd(fd, offset, whence, &handled);
    if (handled) {
        return ampr_klog_io_hook_result("lseek", posix_result_from_pack(rc));
    }
    KernelLseekFn fn = real_lseek();
    return ampr_klog_io_hook_result(
        "lseek",
        fn ? fn(fd, offset, whence) : posix_missing_original<off_t>());
}
"""
pack_lseek_insert = """extern "C" off_t posix_lseek_emul(int fd, off_t offset, int whence) {
    static std::atomic<uint64_t> diagLseekSeq{0};
    bool handled = false;
    const off_t packRc = ampr_pack_try_lseek_fd(fd, offset, whence, &handled);
    off_t result = 0;
    if (handled) {
        result = posix_result_from_pack(packRc);
    } else {
        KernelLseekFn fn = real_lseek();
        result = fn ? fn(fd, offset, whence) : posix_missing_original<off_t>();
    }
#if AMPR_EMU_PACK_IO_COMPAT_DIAGNOSTICS
    const uint64_t seq = diagLseekSeq.fetch_add(1, std::memory_order_relaxed) + 1;
    if (seq <= 192 || result < 0) {
        AMPR_KLOGF(
            "[AMPR_FS] lseek seq=%llu fd=%d off=%lld whence=%d handled=%u rc=%lld errno=%d",
            (unsigned long long)seq, fd, (long long)offset, whence,
            handled ? 1u : 0u, (long long)result, errno);
    }
#endif
    return ampr_klog_io_hook_result("lseek", result);
}
"""
replace_once(PACK, pack_lseek_anchor, pack_lseek_insert)

pack_pread_anchor = """extern "C" ssize_t posix_pread_emul(int fd, void* buffer, size_t size,
                                      off_t offset) {
    bool handled = false;
    const ssize_t rc = ampr_pack_try_pread_fd(
        fd, buffer, size, offset, &handled);
    if (handled) {
        return ampr_klog_io_hook_result("pread", posix_result_from_pack(rc));
    }
    KernelPreadFn fn = real_pread();
    return ampr_klog_io_hook_result(
        "pread",
        fn ? fn(fd, buffer, size, offset)
           : posix_missing_original<ssize_t>());
}
"""
pack_pread_insert = """extern "C" ssize_t posix_pread_emul(int fd, void* buffer, size_t size,
                                      off_t offset) {
    static std::atomic<uint64_t> diagPreadSeq{0};
    bool handled = false;
    const ssize_t packRc = ampr_pack_try_pread_fd(
        fd, buffer, size, offset, &handled);
    ssize_t result = 0;
    if (handled) {
        result = posix_result_from_pack(packRc);
    } else {
        KernelPreadFn fn = real_pread();
        result = fn ? fn(fd, buffer, size, offset)
                    : posix_missing_original<ssize_t>();
    }
#if AMPR_EMU_PACK_IO_COMPAT_DIAGNOSTICS
    const uint64_t seq = diagPreadSeq.fetch_add(1, std::memory_order_relaxed) + 1;
    if (seq <= 256 || result < 0 || (result >= 0 && (size_t)result != size)) {
        AMPR_KLOGF(
            "[AMPR_FS] pread seq=%llu fd=%d off=%lld req=0x%llx handled=%u rc=%lld short=%u errno=%d",
            (unsigned long long)seq, fd, (long long)offset,
            (unsigned long long)size, handled ? 1u : 0u,
            (long long)result,
            (result >= 0 && (size_t)result != size) ? 1u : 0u,
            errno);
    }
#endif
    return ampr_klog_io_hook_result("pread", result);
}
"""
replace_once(PACK, pack_pread_anchor, pack_pread_insert)

pack_read_anchor = """extern "C" ssize_t posix_read_emul(int fd, void* buffer, size_t size) {
    bool handled = false;
    const ssize_t rc = ampr_pack_try_read_fd(fd, buffer, size, &handled);
    if (handled) {
        return ampr_klog_io_hook_result("read", posix_result_from_pack(rc));
    }
    KernelReadFn fn = real_read();
    return ampr_klog_io_hook_result(
        "read",
        fn ? fn(fd, buffer, size) : posix_missing_original<ssize_t>());
}
"""
pack_read_insert = """extern "C" ssize_t posix_read_emul(int fd, void* buffer, size_t size) {
    static std::atomic<uint64_t> diagReadSeq{0};
    bool handled = false;
    const ssize_t packRc = ampr_pack_try_read_fd(fd, buffer, size, &handled);
    ssize_t result = 0;
    if (handled) {
        result = posix_result_from_pack(packRc);
    } else {
        KernelReadFn fn = real_read();
        result = fn ? fn(fd, buffer, size) : posix_missing_original<ssize_t>();
    }
#if AMPR_EMU_PACK_IO_COMPAT_DIAGNOSTICS
    const uint64_t seq = diagReadSeq.fetch_add(1, std::memory_order_relaxed) + 1;
    if (seq <= 256 || result < 0 || (result >= 0 && (size_t)result != size)) {
        AMPR_KLOGF(
            "[AMPR_FS] read seq=%llu fd=%d req=0x%llx handled=%u rc=%lld short=%u errno=%d",
            (unsigned long long)seq, fd, (unsigned long long)size,
            handled ? 1u : 0u, (long long)result,
            (result >= 0 && (size_t)result != size) ? 1u : 0u,
            errno);
    }
#endif
    return ampr_klog_io_hook_result("read", result);
}
"""
replace_once(PACK, pack_read_anchor, pack_read_insert)

backing_open_anchor = """    int fd = openFn(path, SCE_KERNEL_O_RDONLY | O_NONBLOCK,
                    static_cast<SceKernelMode>(0));
    if (fd >= 0) {
        ampr_index_fd_pack_note_open();
    }
    SceKernelStat stat{};
    const int statRc = fd >= 0 ? fstatFn(fd, &stat) : fd;
"""
backing_open_insert = """    int fd = openFn(path, SCE_KERNEL_O_RDONLY | O_NONBLOCK,
                    static_cast<SceKernelMode>(0));
    if (fd >= 0) {
        ampr_index_fd_pack_note_open();
    }
    SceKernelStat stat{};
    const int statRc = fd >= 0 ? fstatFn(fd, &stat) : fd;
#if AMPR_EMU_PACK_IO_COMPAT_DIAGNOSTICS
    AMPR_KLOGF(
        "[AMPR_FS] backing.open path=%s flags=0x%x fd=%d stat_rc=%d size=%lld mode=0%o errno=%d",
        path ? path : "(null)",
        (unsigned)(SCE_KERNEL_O_RDONLY | O_NONBLOCK),
        fd,
        statRc,
        (long long)((statRc == 0) ? stat.st_size : -1),
        (unsigned)((statRc == 0) ? stat.st_mode : 0),
        errno);
#endif
"""
replace_once(PACK, backing_open_anchor, backing_open_insert)


# Directory enumeration is critical for engines that discover content by scanning
# /app0 subdirectories. Log both real and virtual/hybrid directory reads, including
# returned names, and expose whether the AMPR manifest was resident at open time.
getdents_anchor = """extern "C" int posix_getdents_emul(int fd, char* buffer, int size) {
    bool handled = false;
    const int rc = ampr_pack_try_getdents_fd(fd, buffer, size, &handled);
    if (handled) {
        return ampr_klog_io_hook_result("getdents",
                                        posix_result_from_pack(rc));
    }
    KernelGetdentsFn fn = real_getdents();
    return ampr_klog_io_hook_result(
        "getdents",
        fn ? fn(fd, buffer, size) : posix_missing_original<int>());
}
"""
getdents_insert = """extern "C" int posix_getdents_emul(int fd, char* buffer, int size) {
    static std::atomic<uint64_t> diagGetdentsSeq{0};
    bool handled = false;
    const int packRc = ampr_pack_try_getdents_fd(fd, buffer, size, &handled);
    int result = 0;
    if (handled) {
        result = posix_result_from_pack(packRc);
    } else {
        KernelGetdentsFn fn = real_getdents();
        result = fn ? fn(fd, buffer, size) : posix_missing_original<int>();
    }
#if AMPR_EMU_PACK_IO_COMPAT_DIAGNOSTICS
    const uint64_t seq = diagGetdentsSeq.fetch_add(1, std::memory_order_relaxed) + 1;
    AMPR_KLOGF("[AMPR_DIR] getdents seq=%llu fd=%d req=%d handled=%u rc=%d errno=%d",
               (unsigned long long)seq, fd, size, handled ? 1u : 0u, result, errno);
    if (result > 0 && buffer && seq <= 96) {
        size_t input = 0;
        unsigned emitted = 0;
        while (input < (size_t)result && emitted < 32) {
            const struct dirent* entry =
                reinterpret_cast<const struct dirent*>(buffer + input);
            const size_t recordSize = entry->d_reclen;
            if (recordSize < offsetof(struct dirent, d_name) + 1u ||
                recordSize > (size_t)result - input) {
                AMPR_KLOGF("[AMPR_DIR] malformed seq=%llu at=%llu reclen=%llu remaining=%llu",
                           (unsigned long long)seq,
                           (unsigned long long)input,
                           (unsigned long long)recordSize,
                           (unsigned long long)((size_t)result - input));
                break;
            }
            AMPR_KLOGF("[AMPR_DIR] entry seq=%llu n=%u type=%u namlen=%u name=%s",
                       (unsigned long long)seq, emitted,
                       (unsigned)entry->d_type, (unsigned)entry->d_namlen,
                       entry->d_name);
            input += recordSize;
            ++emitted;
        }
    }
#endif
    return ampr_klog_io_hook_result("getdents", result);
}
"""
replace_once(PACK, getdents_anchor, getdents_insert)

getdir_anchor = """extern "C" int posix_getdirentries_emul(int fd, char* buffer, int size,
                                          long* basep) {
    bool handled = false;
    const int rc = ampr_pack_try_getdirentries_fd(
        fd, buffer, size, basep, &handled);
    if (handled) {
        return ampr_klog_io_hook_result("getdirentries",
                                        posix_result_from_pack(rc));
    }
    KernelGetdirentriesFn fn = real_getdirentries();
    return ampr_klog_io_hook_result(
        "getdirentries",
        fn ? fn(fd, buffer, size, basep) : posix_missing_original<int>());
}
"""
getdir_insert = """extern "C" int posix_getdirentries_emul(int fd, char* buffer, int size,
                                          long* basep) {
    static std::atomic<uint64_t> diagGetdirSeq{0};
    bool handled = false;
    const int packRc = ampr_pack_try_getdirentries_fd(
        fd, buffer, size, basep, &handled);
    int result = 0;
    if (handled) {
        result = posix_result_from_pack(packRc);
    } else {
        KernelGetdirentriesFn fn = real_getdirentries();
        result = fn ? fn(fd, buffer, size, basep) : posix_missing_original<int>();
    }
#if AMPR_EMU_PACK_IO_COMPAT_DIAGNOSTICS
    const uint64_t seq = diagGetdirSeq.fetch_add(1, std::memory_order_relaxed) + 1;
    AMPR_KLOGF("[AMPR_DIR] getdirentries seq=%llu fd=%d req=%d handled=%u rc=%d base=%lld errno=%d",
               (unsigned long long)seq, fd, size, handled ? 1u : 0u, result,
               (long long)(basep ? *basep : -1), errno);
#endif
    return ampr_klog_io_hook_result("getdirentries", result);
}
"""
replace_once(PACK, getdir_anchor, getdir_insert)

close_anchor = """extern "C" int posix_close_emul(int fd) {
    bool handled = false;
    const int rc = ampr_pack_try_close_fd(fd, &handled);
    if (handled) {
        return ampr_klog_io_hook_result("close", posix_result_from_pack(rc));
    }
    KernelCloseFn fn = real_close();
    return ampr_klog_io_hook_result(
        "close", fn ? fn(fd) : posix_missing_original<int>());
}
"""
close_insert = """extern "C" int posix_close_emul(int fd) {
    static std::atomic<uint64_t> diagCloseSeq{0};
    bool handled = false;
    const int packRc = ampr_pack_try_close_fd(fd, &handled);
    int result = 0;
    if (handled) {
        result = posix_result_from_pack(packRc);
    } else {
        KernelCloseFn fn = real_close();
        result = fn ? fn(fd) : posix_missing_original<int>();
    }
#if AMPR_EMU_PACK_IO_COMPAT_DIAGNOSTICS
    const uint64_t seq = diagCloseSeq.fetch_add(1, std::memory_order_relaxed) + 1;
    if (seq <= 192 || result < 0) {
        AMPR_KLOGF("[AMPR_FS] close seq=%llu fd=%d handled=%u rc=%d errno=%d",
                   (unsigned long long)seq, fd, handled ? 1u : 0u, result, errno);
    }
#endif
    return ampr_klog_io_hook_result("close", result);
}
"""
replace_once(PACK, close_anchor, close_insert)

reach_anchor = """extern "C" int sceKernelCheckReachability_emul(const char* path) {
    bool expectedIndexMiss = false;
    const int result = sceKernelCheckReachability_impl(
        path, &expectedIndexMiss);
    return expectedIndexMiss
        ? result
        : ampr_klog_io_hook_path_result(
              "sceKernelCheckReachability", path, result);
}
"""
reach_insert = """extern "C" int sceKernelCheckReachability_emul(const char* path) {
    static std::atomic<uint64_t> diagReachSeq{0};
    bool expectedIndexMiss = false;
    const int result = sceKernelCheckReachability_impl(
        path, &expectedIndexMiss);
#if AMPR_EMU_PACK_IO_COMPAT_DIAGNOSTICS
    const uint64_t seq = diagReachSeq.fetch_add(1, std::memory_order_relaxed) + 1;
    if (seq <= 192 || result < 0) {
        AMPR_KLOGF("[AMPR_FS] reach seq=%llu path=%s rc=%d index_miss=%u manifest_ready=%u errno=%d",
                   (unsigned long long)seq, ampr_log_path_arg(path), result,
                   expectedIndexMiss ? 1u : 0u,
                   ampr_pack_manifest_is_resident_ready() ? 1u : 0u,
                   errno);
    }
#endif
    return expectedIndexMiss
        ? result
        : ampr_klog_io_hook_path_result(
              "sceKernelCheckReachability", path, result);
}
"""
replace_once(INDEX, reach_anchor, reach_insert)

# Add manifest readiness to every open trace; this is key to detecting a race
# where a physical directory is exposed before the packed overlay is publishable.
s_open = """            "[AMPR_FS] open seq=%llu path=%s flags=0x%x mode=0%o rc=%d index_miss=%u errno=%d",
            (unsigned long long)seq,
            ampr_log_path_arg(path),
            flags,
            (unsigned)mode,
            result,
            expectedIndexMiss ? 1u : 0u,
            errno);"""
s_open_new = """            "[AMPR_FS] open seq=%llu path=%s flags=0x%x mode=0%o rc=%d index_miss=%u manifest_ready=%u errno=%d",
            (unsigned long long)seq,
            ampr_log_path_arg(path),
            flags,
            (unsigned)mode,
            result,
            expectedIndexMiss ? 1u : 0u,
            ampr_pack_manifest_is_resident_ready() ? 1u : 0u,
            errno);"""
replace_once(INDEX, s_open, s_open_new)


# Eagerly initialize the pack manifest during module_start. The EXLZ regression
# shows /app0 directory enumeration occurring while manifest_ready=0, so the
# directory overlay is bypassed and physical getdents wins. module_start is a
# safe initialization boundary and should publish the manifest before game I/O.
module_start_anchor = """int module_start(size_t args, const void* argp) {
    (void)args;
    (void)argp;
    return amprInstallLibkernelHooks();
}
"""
module_start_insert = """int module_start(size_t args, const void* argp) {
    (void)args;
    (void)argp;
#if AMPR_EMU_PACK_ENABLE
    // ShadowMount/EXLZ can expose the PRX before the rest of /app0 is fully
    // visible. Probe the loose AMPR index before installing hooks so a transient
    // ENOENT cannot poison the manifest state as permanently unavailable.
    bool indexVisible = false;
    int probeRc = -1;
    for (unsigned attempt = 0; attempt < 300; ++attempt) {
        probeRc = sceKernelOpen(AMPR_EMU_PACK_INDEX_PATH,
                                SCE_KERNEL_O_RDONLY,
                                static_cast<SceKernelMode>(0));
        if (probeRc >= 0) {
            (void)sceKernelClose(probeRc);
            indexVisible = true;
            break;
        }
        (void)sceKernelUsleep(10000u);
    }
    AMPR_KLOGF("[AMPR_INIT] index-visible=%u probe_rc=%d",
               indexVisible ? 1u : 0u, probeRc);
#endif
    const int hookRc = amprInstallLibkernelHooks();
    if (hookRc != 0) {
        AMPR_KLOGF("[AMPR_INIT] hooks rc=%d", hookRc);
        return hookRc;
    }
#if AMPR_EMU_PACK_ENABLE
    const bool manifestReady =
        indexVisible && ampr_pack_ensure_manifest_ready_safe();
    AMPR_KLOGF("[AMPR_INIT] delayed-manifest ready=%u",
               manifestReady ? 1u : 0u);
#endif
    return 0;
}
"""
replace_once(EXPORTS, module_start_anchor, module_start_insert)

print("Applied exhaustive AMPR diagnostics + delayed manifest initialization")



