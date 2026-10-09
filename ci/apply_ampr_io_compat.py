#!/usr/bin/env python3
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1] / "ampr_emu"
CONFIG = ROOT / "include" / "ampr_emu_config.h"
PACK = ROOT / "src" / "ampr_emu_pack.cpp"
HOOK = ROOT / "src" / "ampr_libkernel_hook.cpp"
HOOK_HEADER = ROOT / "include" / "ampr_libkernel_hook.h"
INDEX = ROOT / "src" / "ampr_emu_index.cpp"
EXPORTS = ROOT / "src" / "sceampr_exports.cpp"
APR_BRIDGE = ROOT / "src" / "ampr_emu_apr_kernel_bridge.cpp"
APR_REACTOR = ROOT / "src" / "ampr_emu_apr_reactor.cpp"
APR_SERVICES = ROOT / "src" / "ampr_emu_apr_services.cpp"


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
exports_include_anchor = """#include <new>
"""
exports_include_insert = """#include <new>
#include <atomic>
"""
replace_once(EXPORTS, exports_include_anchor, exports_include_insert)

exports_runtime_mem_anchor = """#include "ampr_emu_log.h"
"""
exports_runtime_mem_insert = """#include "ampr_emu_log.h"
#include "ampr_emu_runtime_memory.h"
"""
replace_once(EXPORTS, exports_runtime_mem_anchor, exports_runtime_mem_insert)

module_start_anchor = """int module_start(size_t args, const void* argp) {
    (void)args;
    (void)argp;
    return amprInstallLibkernelHooks();
}
"""
module_start_insert = """#if AMPR_EMU_PACK_ENABLE
static std::atomic<bool> g_manifestLoaderStop{false};
static ScePthread g_manifestLoaderThread{};
static bool g_manifestLoaderStarted = false;

static void* ampr_manifest_loader_main(void*) {
    bool ready = false;
    unsigned attempts = 0;

    // load_manifest() allocates the whole manifest from AMPR's internal pool.
    // This async thread can run before the normal app0-index path initializes
    // that pool, which produces memory=null/alloc=0 and poisons loadState as
    // invalid. Initialize the shared static pool first.
    const bool poolReady =
        ampr_internal_amm_pool_prepare_static_storage("async-manifest.loader");
    AMPR_KLOGF("[AMPR_INIT] async-pool ready=%u",
               poolReady ? 1u : 0u);
    if (!poolReady) {
        return nullptr;
    }

    for (; attempts < 2000 &&
           !g_manifestLoaderStop.load(std::memory_order_acquire);
         ++attempts) {
        // ensure_manifest_ready reaches load_manifest(), which uses
        // real_open()/real_fstat()/real_pread for the physical backing.
        ready = ampr_pack_ensure_manifest_ready_safe();
        if (ready) break;
        (void)sceKernelUsleep(10000u);
    }
    AMPR_KLOGF("[AMPR_INIT] async-manifest ready=%u attempts=%u",
               ready ? 1u : 0u, attempts + (ready ? 1u : 0u));
    return nullptr;
}
#endif

int module_start(size_t args, const void* argp) {
    (void)args;
    (void)argp;
    const int hookRc = amprInstallLibkernelHooks();
    if (hookRc != 0) {
        AMPR_KLOGF("[AMPR_INIT] hooks rc=%d", hookRc);
        return hookRc;
    }
#if AMPR_EMU_PACK_ENABLE
    g_manifestLoaderStop.store(false, std::memory_order_release);
    const int threadRc = scePthreadCreate(
        &g_manifestLoaderThread,
        nullptr,
        ampr_manifest_loader_main,
        nullptr,
        "ampr_manifest_loader");
    g_manifestLoaderStarted = (threadRc == 0);
    AMPR_KLOGF("[AMPR_INIT] async-loader thread_rc=%d started=%u",
               threadRc, g_manifestLoaderStarted ? 1u : 0u);
#endif
    return 0;
}
"""
replace_once(EXPORTS, module_start_anchor, module_start_insert)


# Make an initial ENOENT non-terminal. On EXLZ/ShadowMount the runtime can start
# before /app0 is fully populated; treating that first miss as permanently
# unavailable prevents AMPR from ever serving packed files later in the same run.
pack_retry_anchor = """        if (current == kPackLoadReady) return true;
        if (current == kPackLoadUnavailable || current == kPackLoadInvalid) return false;
        uint32_t expected = kPackLoadUninitialized;
"""
pack_retry_insert = """        if (current == kPackLoadReady) return true;
        if (current == kPackLoadInvalid) return false;
        if (current == kPackLoadUnavailable) {
            uint32_t unavailable = kPackLoadUnavailable;
            if (!state.loadState.compare_exchange_strong(
                    unavailable, kPackLoadUninitialized,
                    std::memory_order_acq_rel,
                    std::memory_order_acquire)) {
                continue;
            }
            AMPR_KLOGF("[AMPR_INIT] manifest retry after transient unavailable");
        }
        uint32_t expected = kPackLoadUninitialized;
"""
replace_once(PACK, pack_retry_anchor, pack_retry_insert)


# Make manifest-loading failures visible even when normal AMPR debug logging is off.
# This distinguishes transient ENOENT from stat/read/layout/profile/directory-index failures.
manifest_open_anchor = """    const int fd = openFn(AMPR_EMU_PACK_INDEX_PATH,
                          SCE_KERNEL_O_RDONLY, static_cast<SceKernelMode>(0));
    if (fd < 0) {
        const int openErrno = fd == -1 ? errno : ampr_posix_errno_from_sce(fd);
"""
manifest_open_insert = """    const int fd = openFn(AMPR_EMU_PACK_INDEX_PATH,
                          SCE_KERNEL_O_RDONLY, static_cast<SceKernelMode>(0));
    if (fd < 0) {
        const int openErrno = fd == -1 ? errno : ampr_posix_errno_from_sce(fd);
#if AMPR_EMU_PACK_IO_COMPAT_DIAGNOSTICS
        AMPR_KLOGF("[AMPR_MANIFEST] open.fail path=%s rc=%d errno=%d",
                   AMPR_EMU_PACK_INDEX_PATH, fd, openErrno);
#endif
"""
replace_once(PACK, manifest_open_anchor, manifest_open_insert)

manifest_stat_anchor = """    if (statRc != 0 || stat.st_size < static_cast<off_t>(sizeof(AmprPackIndexHeader)) ||
        static_cast<uint64_t>(stat.st_size) > AMPR_EMU_PACK_INDEX_MAX_BYTES) {
        (void)closeFn(fd);
"""
manifest_stat_insert = """    if (statRc != 0 || stat.st_size < static_cast<off_t>(sizeof(AmprPackIndexHeader)) ||
        static_cast<uint64_t>(stat.st_size) > AMPR_EMU_PACK_INDEX_MAX_BYTES) {
#if AMPR_EMU_PACK_IO_COMPAT_DIAGNOSTICS
        AMPR_KLOGF("[AMPR_MANIFEST] stat.fail rc=%d size=%lld errno=%d",
                   statRc, (long long)(statRc == 0 ? stat.st_size : -1), errno);
#endif
        (void)closeFn(fd);
"""
replace_once(PACK, manifest_stat_anchor, manifest_stat_insert)

manifest_read_anchor = """    if (!memory || actual < bytes || !pread_exact(fd, memory, bytes, 0)) {
        if (memory) (void)ampr_internal_amm_pool_free(memory, "apr.pack.index.fail");
"""
manifest_read_insert = """    if (!memory || actual < bytes || !pread_exact(fd, memory, bytes, 0)) {
#if AMPR_EMU_PACK_IO_COMPAT_DIAGNOSTICS
        AMPR_KLOGF("[AMPR_MANIFEST] read.fail bytes=%llu alloc=%llu memory=%p errno=%d",
                   (unsigned long long)bytes,
                   (unsigned long long)actual,
                   memory,
                   errno);
#endif
        if (memory) (void)ampr_internal_amm_pool_free(memory, "apr.pack.index.fail");
"""
replace_once(PACK, manifest_read_anchor, manifest_read_insert)

manifest_layout_anchor = """    if (!validate_manifest_layout(state, memory, bytes)) {
        (void)ampr_internal_amm_pool_free(memory, "apr.pack.index.invalid");
"""
manifest_layout_insert = """    if (!validate_manifest_layout(state, memory, bytes)) {
#if AMPR_EMU_PACK_IO_COMPAT_DIAGNOSTICS
        AMPR_KLOGF("[AMPR_MANIFEST] layout.invalid bytes=%llu",
                   (unsigned long long)bytes);
#endif
        (void)ampr_internal_amm_pool_free(memory, "apr.pack.index.invalid");
"""
replace_once(PACK, manifest_layout_anchor, manifest_layout_insert)

manifest_profile_anchor = """    if (!load_runtime_profile(state)) {
        release_manifest_storage(state);
        return false;
    }
"""
manifest_profile_insert = """    if (!load_runtime_profile(state)) {
#if AMPR_EMU_PACK_IO_COMPAT_DIAGNOSTICS
        AMPR_KLOGF("[AMPR_MANIFEST] profile.invalid-or-unreadable");
#endif
        release_manifest_storage(state);
        return false;
    }
"""
replace_once(PACK, manifest_profile_anchor, manifest_profile_insert)

manifest_order_anchor = """    if (!build_packed_file_order(state)) {
        AMPR_CRITICAL_LOGF("apr.pack.directory-index.fail files=%llu",
"""
manifest_order_insert = """    if (!build_packed_file_order(state)) {
#if AMPR_EMU_PACK_IO_COMPAT_DIAGNOSTICS
        AMPR_KLOGF("[AMPR_MANIFEST] directory-index.fail files=%llu",
                   (unsigned long long)state.header->fileCount);
#endif
        AMPR_CRITICAL_LOGF("apr.pack.directory-index.fail files=%llu",
"""
replace_once(PACK, manifest_order_anchor, manifest_order_insert)

manifest_success_anchor = """    AMPR_LOGF("apr.pack.index.loaded path=%s files=%llu packed=%u loose=%llu chunks=%llu packs=%u bytes=0x%llx dirOverlay=%u processOpen=%u processAio=%u processSync=%u",
"""
manifest_success_insert = """#if AMPR_EMU_PACK_IO_COMPAT_DIAGNOSTICS
    AMPR_KLOGF("[AMPR_MANIFEST] loaded path=%s files=%llu packed=%u chunks=%llu packs=%u bytes=%llu",
               AMPR_EMU_PACK_INDEX_PATH,
               (unsigned long long)state.header->fileCount,
               state.packedFileCount,
               (unsigned long long)state.header->chunkCount,
               state.header->packCount,
               (unsigned long long)bytes);
#endif
    AMPR_LOGF("apr.pack.index.loaded path=%s files=%llu packed=%u loose=%llu chunks=%llu packs=%u bytes=0x%llx dirOverlay=%u processOpen=%u processAio=%u processSync=%u",
"""
replace_once(PACK, manifest_success_anchor, manifest_success_insert)

# Log retry state at low volume so a crash before the 20-second timeout still
# tells us whether the async loader is alive and what it is observing.
async_anchor = """        ready = ampr_pack_ensure_manifest_ready_safe();
        if (ready) break;
        (void)sceKernelUsleep(10000u);
"""
async_insert = """        ready = ampr_pack_ensure_manifest_ready_safe();
#if AMPR_EMU_PACK_IO_COMPAT_DIAGNOSTICS
        if (attempts < 16 || ((attempts + 1u) % 100u) == 0u || ready) {
            AMPR_KLOGF("[AMPR_INIT] async-attempt=%u ready=%u",
                       attempts + 1u, ready ? 1u : 0u);
        }
#endif
        if (ready) break;
        (void)sceKernelUsleep(10000u);
"""
replace_once(EXPORTS, async_anchor, async_insert)


# Preserve real directory metadata for hybrid directory wrappers. When a
# physical directory is wrapped only to overlay virtual packed children, fstat
# must describe the underlying directory rather than a synthetic zero-sized,
# read-only directory. Some engines validate directory metadata immediately
# after enumeration.
hybrid_fstat_anchor = """        const VirtualDirectorySlot& slot = state.virtualDirectories[index];
        if (!slot.active || slot.generation != generation) {
            return SCE_KERNEL_ERROR_EBADF;
        }
        fill_synthetic_stat(stat, true, 0, 0,
                            folded_hash(slot.path, slot.pathLength));
        return 0;
"""
hybrid_fstat_insert = """        const VirtualDirectorySlot& slot = state.virtualDirectories[index];
        if (!slot.active || slot.generation != generation) {
            return SCE_KERNEL_ERROR_EBADF;
        }
        if (slot.realFd >= 0) {
            KernelFstatFn fn = real_fstat();
            if (!fn) return SCE_KERNEL_ERROR_EIO;
            const int rc = fn(slot.realFd, stat);
#if AMPR_EMU_PACK_IO_COMPAT_DIAGNOSTICS
            AMPR_KLOGF("[AMPR_DIR] hybrid.fstat vfd=0x%x realfd=%d rc=%d size=%lld mode=0%o",
                       (unsigned)fd,
                       slot.realFd,
                       rc,
                       (long long)(rc == 0 ? stat->st_size : -1),
                       rc == 0 ? (unsigned)stat->st_mode : 0u);
#endif
            return rc == -1 ? ampr_sce_errno_from_posix(errno) : rc;
        }
        fill_synthetic_stat(stat, true, 0, 0,
                            folded_hash(slot.path, slot.pathLength));
        return 0;
"""
replace_once(PACK, hybrid_fstat_anchor, hybrid_fstat_insert)


# Merge physical and virtual directory entries into the same getdents result
# whenever space permits. The previous hybrid implementation returned as soon
# as it had any physical entries, so callers that treat a short getdents result
# as end-of-directory never saw packed-only children (for example .ucas files).
hybrid_dir_anchor = """    while (!slot.realExhausted && slot.realFd >= 0) {
        long physicalBase = slot.directoryOffset;
        int rc = SCE_KERNEL_ERROR_EIO;
        if (useGetdirentries) {
            if (!getdirentriesFn) return SCE_KERNEL_ERROR_EIO;
            rc = getdirentriesFn(slot.realFd, buffer, size, &physicalBase);
        } else {
            if (!getdentsFn) return SCE_KERNEL_ERROR_EIO;
            rc = getdentsFn(slot.realFd, buffer, size);
        }
        if (rc < 0) return rc;
        if (useGetdirentries) {
            slot.directoryOffset = advance_directory_offset(physicalBase, rc);
        } else if (KernelLseekFn lseekFn = real_lseek()) {
            const off_t current = lseekFn(slot.realFd, 0, SEEK_CUR);
            if (current >= 0 &&
                static_cast<uint64_t>(current) <=
                    static_cast<uint64_t>((std::numeric_limits<long>::max)())) {
                slot.directoryOffset = static_cast<long>(current);
            } else {
                slot.directoryOffset = advance_directory_offset(
                    slot.directoryOffset, rc);
            }
        } else {
            slot.directoryOffset = advance_directory_offset(
                slot.directoryOffset, rc);
        }
        if (rc == 0) {
            slot.realExhausted = true;
            break;
        }
        size_t input = 0;
        size_t output = 0;
        while (input < static_cast<size_t>(rc)) {
            auto* entry = reinterpret_cast<struct dirent*>(buffer + input);
            const size_t recordSize = entry->d_reclen;
            if (recordSize < offsetof(struct dirent, d_name) + 1u ||
                recordSize > static_cast<size_t>(rc) - input ||
                static_cast<size_t>(entry->d_namlen) + 1u >
                    recordSize - offsetof(struct dirent, d_name)) {
                return SCE_KERNEL_ERROR_EIO;
            }
            const size_t nameLength = entry->d_namlen;
            const bool hidden = service_name_hidden(
                state, slot.path, slot.pathLength, entry->d_name, nameLength);
            if (hidden) {
                state.stats.directoryHiddenEntries.fetch_add(
                    1, std::memory_order_relaxed);
            } else {
                directory_record_physical_name(
                    slot, entry->d_name, nameLength);
                if (output != input) {
                    std::memmove(buffer + output, entry, recordSize);
                }
                output += recordSize;
                state.stats.directoryPhysicalEntries.fetch_add(
                    1, std::memory_order_relaxed);
            }
            input += recordSize;
        }
        if (output != 0) {
            if (basep) *basep = physicalBase;
#if AMPR_EMU_PACK_IO_LOG
            AMPR_LOGF("apr.pack.dir.%s path=%s vfd=0x%x phase=physical bytes=%llu base=%lld",
                      useGetdirentries ? "getdirentries" : "getdents",
                      slot.path, (unsigned)fd,
                      (unsigned long long)output,
                      (long long)physicalBase);
#endif
            return static_cast<int>(output);
        }
    }

    size_t output = 0;
"""
hybrid_dir_insert = """    size_t output = 0;
    while (!slot.realExhausted && slot.realFd >= 0 &&
           output < static_cast<size_t>(size)) {
        const size_t remaining = static_cast<size_t>(size) - output;
        char* const physicalBuffer = buffer + output;
        long physicalBase = slot.directoryOffset;
        int rc = SCE_KERNEL_ERROR_EIO;
        if (useGetdirentries) {
            if (!getdirentriesFn) return SCE_KERNEL_ERROR_EIO;
            rc = getdirentriesFn(slot.realFd, physicalBuffer,
                                 static_cast<int>(remaining), &physicalBase);
        } else {
            if (!getdentsFn) return SCE_KERNEL_ERROR_EIO;
            rc = getdentsFn(slot.realFd, physicalBuffer,
                            static_cast<int>(remaining));
        }
        if (rc < 0) return rc;
        if (useGetdirentries) {
            slot.directoryOffset = advance_directory_offset(physicalBase, rc);
        } else if (KernelLseekFn lseekFn = real_lseek()) {
            const off_t current = lseekFn(slot.realFd, 0, SEEK_CUR);
            if (current >= 0 &&
                static_cast<uint64_t>(current) <=
                    static_cast<uint64_t>((std::numeric_limits<long>::max)())) {
                slot.directoryOffset = static_cast<long>(current);
            } else {
                slot.directoryOffset = advance_directory_offset(
                    slot.directoryOffset, rc);
            }
        } else {
            slot.directoryOffset = advance_directory_offset(
                slot.directoryOffset, rc);
        }
        if (rc == 0) {
            slot.realExhausted = true;
            break;
        }

        size_t input = 0;
        size_t compacted = 0;
        while (input < static_cast<size_t>(rc)) {
            auto* entry = reinterpret_cast<struct dirent*>(
                physicalBuffer + input);
            const size_t recordSize = entry->d_reclen;
            if (recordSize < offsetof(struct dirent, d_name) + 1u ||
                recordSize > static_cast<size_t>(rc) - input ||
                static_cast<size_t>(entry->d_namlen) + 1u >
                    recordSize - offsetof(struct dirent, d_name)) {
                return SCE_KERNEL_ERROR_EIO;
            }
            const size_t nameLength = entry->d_namlen;
            const bool hidden = service_name_hidden(
                state, slot.path, slot.pathLength, entry->d_name, nameLength);
            if (hidden) {
                state.stats.directoryHiddenEntries.fetch_add(
                    1, std::memory_order_relaxed);
            } else {
                directory_record_physical_name(
                    slot, entry->d_name, nameLength);
                if (compacted != input) {
                    std::memmove(physicalBuffer + compacted,
                                 entry, recordSize);
                }
                compacted += recordSize;
                state.stats.directoryPhysicalEntries.fetch_add(
                    1, std::memory_order_relaxed);
            }
            input += recordSize;
        }
        output += compacted;

        // If filtering consumed the whole returned batch but there is still
        // room, keep draining the physical directory. Otherwise continue too:
        // a single emulated getdents should expose the complete merged view
        // whenever the caller supplied enough space.
        if (output >= static_cast<size_t>(size)) {
            break;
        }
    }

#if AMPR_EMU_PACK_IO_COMPAT_DIAGNOSTICS
    if (output != 0) {
        AMPR_KLOGF("[AMPR_DIR] merge.physical vfd=0x%x bytes=%llu exhausted=%u",
                   (unsigned)fd,
                   (unsigned long long)output,
                   slot.realExhausted ? 1u : 0u);
    }
#endif
"""
replace_once(PACK, hybrid_dir_anchor, hybrid_dir_insert)


# Cover the sceKernel* filesystem entry points as aliases of the POSIX hooks.
# Some games enumerate through getdents and then open/stat/read files using
# sceKernelOpen/sceKernelStat/sceKernelRead rather than the POSIX symbols.
# Without these aliases packed-only files can be visible in directory listings
# but still fail immediately when the game tries to access them.
hook_alias_anchor = """    {"open", reinterpret_cast<void*>(&posix_open_emul), kHookMandatory, {}},
    {"stat", reinterpret_cast<void*>(&posix_stat_emul), kHookMandatory, {}},
"""
hook_alias_insert = """    {"open", reinterpret_cast<void*>(&posix_open_emul), kHookMandatory, {}},
    {"sceKernelOpen", reinterpret_cast<void*>(&posix_open_emul), kHookMandatory, {}},
    {"stat", reinterpret_cast<void*>(&posix_stat_emul), kHookMandatory, {}},
    {"sceKernelStat", reinterpret_cast<void*>(&posix_stat_emul), kHookMandatory, {}},
"""
replace_once(HOOK, hook_alias_anchor, hook_alias_insert)

hook_fd_alias_anchor = """    {"sceKernelClose", reinterpret_cast<void*>(&sceKernelClose_emul), kHookMandatory, {}},
    // sceKernelClose bypasses the public close thunk on current libkernel,
    // therefore both entry points are required for virtual descriptors.
    {"close", reinterpret_cast<void*>(&posix_close_emul), kHookMandatory, {}},
    {"fstat", reinterpret_cast<void*>(&posix_fstat_emul), kHookMandatory, {}},
"""
hook_fd_alias_insert = """    {"sceKernelClose", reinterpret_cast<void*>(&sceKernelClose_emul), kHookMandatory, {}},
    // sceKernelClose bypasses the public close thunk on current libkernel,
    // therefore both entry points are required for virtual descriptors.
    {"close", reinterpret_cast<void*>(&posix_close_emul), kHookMandatory, {}},
    {"fstat", reinterpret_cast<void*>(&posix_fstat_emul), kHookMandatory, {}},
    {"sceKernelFstat", reinterpret_cast<void*>(&posix_fstat_emul), kHookMandatory, {}},
"""
replace_once(HOOK, hook_fd_alias_anchor, hook_fd_alias_insert)

hook_dir_alias_anchor = """    {"getdents", reinterpret_cast<void*>(&posix_getdents_emul), kHookMandatory, {}},
    {"getdirentries", reinterpret_cast<void*>(&posix_getdirentries_emul), kHookMandatory, {}},
"""
hook_dir_alias_insert = """    {"getdents", reinterpret_cast<void*>(&posix_getdents_emul), kHookMandatory, {}},
    {"sceKernelGetdents", reinterpret_cast<void*>(&posix_getdents_emul), kHookMandatory, {}},
    {"getdirentries", reinterpret_cast<void*>(&posix_getdirentries_emul), kHookMandatory, {}},
    {"sceKernelGetdirentries", reinterpret_cast<void*>(&posix_getdirentries_emul), kHookMandatory, {}},
"""
replace_once(HOOK, hook_dir_alias_anchor, hook_dir_alias_insert)

hook_read_alias_anchor = """    {"pread", reinterpret_cast<void*>(&posix_pread_emul), kHookOptional, {}},
    {"preadv", reinterpret_cast<void*>(&posix_preadv_emul), kHookOptional, {}},
    {"read", reinterpret_cast<void*>(&posix_read_emul), kHookOptional, {}},
    {"readv", reinterpret_cast<void*>(&posix_readv_emul), kHookOptional, {}},
"""
hook_read_alias_insert = """    {"pread", reinterpret_cast<void*>(&posix_pread_emul), kHookOptional, {}},
    {"sceKernelPread", reinterpret_cast<void*>(&posix_pread_emul), kHookOptional, {}},
    {"preadv", reinterpret_cast<void*>(&posix_preadv_emul), kHookOptional, {}},
    {"sceKernelPreadv", reinterpret_cast<void*>(&posix_preadv_emul), kHookOptional, {}},
    {"read", reinterpret_cast<void*>(&posix_read_emul), kHookOptional, {}},
    {"sceKernelRead", reinterpret_cast<void*>(&posix_read_emul), kHookOptional, {}},
    {"readv", reinterpret_cast<void*>(&posix_readv_emul), kHookOptional, {}},
    {"sceKernelReadv", reinterpret_cast<void*>(&posix_readv_emul), kHookOptional, {}},
"""
replace_once(HOOK, hook_read_alias_anchor, hook_read_alias_insert)


# Keep HookId ordering and SDK fallback tables aligned with the sceKernel aliases
# added above. The hook implementation relies on exact positional correspondence.
hook_enum_anchor = """    kAmprLibkernelHook_open = 0,
    kAmprLibkernelHook_stat,
"""
hook_enum_insert = """    kAmprLibkernelHook_open = 0,
    kAmprLibkernelHook_sceKernelOpen,
    kAmprLibkernelHook_stat,
    kAmprLibkernelHook_sceKernelStat,
"""
replace_once(HOOK_HEADER, hook_enum_anchor, hook_enum_insert)

hook_enum_fd_anchor = """    kAmprLibkernelHook_sceKernelClose,
    kAmprLibkernelHook_close,
    kAmprLibkernelHook_fstat,
    kAmprLibkernelHook_lseek,
"""
hook_enum_fd_insert = """    kAmprLibkernelHook_sceKernelClose,
    kAmprLibkernelHook_close,
    kAmprLibkernelHook_fstat,
    kAmprLibkernelHook_sceKernelFstat,
    kAmprLibkernelHook_lseek,
"""
replace_once(HOOK_HEADER, hook_enum_fd_anchor, hook_enum_fd_insert)

hook_enum_dir_anchor = """    kAmprLibkernelHook_getdents,
    kAmprLibkernelHook_getdirentries,
"""
hook_enum_dir_insert = """    kAmprLibkernelHook_getdents,
    kAmprLibkernelHook_sceKernelGetdents,
    kAmprLibkernelHook_getdirentries,
    kAmprLibkernelHook_sceKernelGetdirentries,
"""
replace_once(HOOK_HEADER, hook_enum_dir_anchor, hook_enum_dir_insert)

hook_enum_read_anchor = """    kAmprLibkernelHook_pread,
    kAmprLibkernelHook_preadv,
    kAmprLibkernelHook_read,
    kAmprLibkernelHook_readv,
"""
hook_enum_read_insert = """    kAmprLibkernelHook_pread,
    kAmprLibkernelHook_sceKernelPread,
    kAmprLibkernelHook_preadv,
    kAmprLibkernelHook_sceKernelPreadv,
    kAmprLibkernelHook_read,
    kAmprLibkernelHook_sceKernelRead,
    kAmprLibkernelHook_readv,
    kAmprLibkernelHook_sceKernelReadv,
"""
replace_once(HOOK_HEADER, hook_enum_read_anchor, hook_enum_read_insert)

sdk_fallback_anchor = """#define AMPR_LIBKERNEL_SDK_FALLBACKS \\
    nullptr, \\
    nullptr, \\
    reinterpret_cast<void*>(&::sceKernelCheckReachability), \\
"""
sdk_fallback_insert = """#define AMPR_LIBKERNEL_SDK_FALLBACKS \\
    nullptr, \\
    reinterpret_cast<void*>(&::sceKernelOpen), \\
    nullptr, \\
    reinterpret_cast<void*>(&::sceKernelStat), \\
    reinterpret_cast<void*>(&::sceKernelCheckReachability), \\
"""
replace_once(HOOK, sdk_fallback_anchor, sdk_fallback_insert)

fd_fallback_anchor = """#define AMPR_LIBKERNEL_PACK_FD_SDK_FALLBACKS \\
    , nullptr \\
    , nullptr \\
    , nullptr \\
    , nullptr
"""
fd_fallback_insert = """#define AMPR_LIBKERNEL_PACK_FD_SDK_FALLBACKS \\
    , reinterpret_cast<void*>(&::sceKernelClose) \\
    , nullptr \\
    , nullptr \\
    , reinterpret_cast<void*>(&::sceKernelFstat) \\
    , nullptr
"""
replace_once(HOOK, fd_fallback_anchor, fd_fallback_insert)

dir_fallback_anchor = """#define AMPR_LIBKERNEL_PACK_DIRECTORY_SDK_FALLBACKS \\
    , nullptr \\
    , nullptr
"""
dir_fallback_insert = """#define AMPR_LIBKERNEL_PACK_DIRECTORY_SDK_FALLBACKS \\
    , nullptr \\
    , reinterpret_cast<void*>(&::sceKernelGetdents) \\
    , nullptr \\
    , reinterpret_cast<void*>(&::sceKernelGetdirentries)
"""
replace_once(HOOK, dir_fallback_anchor, dir_fallback_insert)

read_fallback_anchor = """#define AMPR_LIBKERNEL_PACK_PROCESS_SYNC_READ_SDK_FALLBACKS \\
    , nullptr \\
    , nullptr \\
    , nullptr \\
    , nullptr
"""
read_fallback_insert = """#define AMPR_LIBKERNEL_PACK_PROCESS_SYNC_READ_SDK_FALLBACKS \\
    , nullptr \\
    , reinterpret_cast<void*>(&::sceKernelPread) \\
    , nullptr \\
    , reinterpret_cast<void*>(&::sceKernelPreadv) \\
    , nullptr \\
    , reinterpret_cast<void*>(&::sceKernelRead) \\
    , nullptr \\
    , reinterpret_cast<void*>(&::sceKernelReadv)
"""
replace_once(HOOK, read_fallback_anchor, read_fallback_insert)


# Trace the remaining file-discovery APIs that can run immediately after
# directory enumeration. Normal AMPR debug macros are disabled in this build,
# so use AMPR_KLOGF directly and keep the output low-volume.
apr_size_anchor = """extern "C" int sceKernelAprGetFileSize_emul(int fileId, uint64_t* outSize) {
    AMPR_TLOGF("lk.apr.getFileSize enter fileId=%d out=%p", fileId, outSize);
"""
apr_size_insert = """extern "C" int sceKernelAprGetFileSize_emul(int fileId, uint64_t* outSize) {
#if AMPR_EMU_PACK_IO_COMPAT_DIAGNOSTICS
    AMPR_KLOGF("[AMPR_CALL] apr.getFileSize enter fileId=%d", fileId);
#endif
    AMPR_TLOGF("lk.apr.getFileSize enter fileId=%d out=%p", fileId, outSize);
"""
replace_once(APR_BRIDGE, apr_size_anchor, apr_size_insert)

apr_stat_anchor = """extern "C" int sceKernelAprGetFileStat_emul(int fileId, SceKernelStat* st) {
    AMPR_TLOGF("lk.apr.getFileStat enter fileId=%d out=%p", fileId, st);
"""
apr_stat_insert = """extern "C" int sceKernelAprGetFileStat_emul(int fileId, SceKernelStat* st) {
#if AMPR_EMU_PACK_IO_COMPAT_DIAGNOSTICS
    AMPR_KLOGF("[AMPR_CALL] apr.getFileStat enter fileId=%d", fileId);
#endif
    AMPR_TLOGF("lk.apr.getFileStat enter fileId=%d out=%p", fileId, st);
"""
replace_once(APR_BRIDGE, apr_stat_anchor, apr_stat_insert)

apr_resolve_anchor = """extern "C" int sceKernelAprResolveFilepathsToIds_emul(const char* path[], uint32_t num, uint32_t ids[], uint32_t* errorIndex) {
    AMPR_VLOGF("lk.apr.resolveIds enter paths=%p num=%u ids=%p errorIndex=%p", path, (unsigned)num, ids, errorIndex);
"""
apr_resolve_insert = """extern "C" int sceKernelAprResolveFilepathsToIds_emul(const char* path[], uint32_t num, uint32_t ids[], uint32_t* errorIndex) {
#if AMPR_EMU_PACK_IO_COMPAT_DIAGNOSTICS
    AMPR_KLOGF("[AMPR_CALL] apr.resolveIds num=%u first=%s",
               (unsigned)num,
               (path && num && path[0]) ? path[0] : "(null)");
#endif
    AMPR_VLOGF("lk.apr.resolveIds enter paths=%p num=%u ids=%p errorIndex=%p", path, (unsigned)num, ids, errorIndex);
"""
replace_once(APR_BRIDGE, apr_resolve_anchor, apr_resolve_insert)

apr_resolve_sizes_anchor = """extern "C" int sceKernelAprResolveFilepathsToIdsAndFileSizes_emul(const char* path[], uint32_t num, uint32_t ids[], size_t fileSizes[], uint32_t* errorIndex) {
    AMPR_VLOGF("lk.apr.resolveIdsSizes enter paths=%p num=%u ids=%p sizes=%p errorIndex=%p",
"""
apr_resolve_sizes_insert = """extern "C" int sceKernelAprResolveFilepathsToIdsAndFileSizes_emul(const char* path[], uint32_t num, uint32_t ids[], size_t fileSizes[], uint32_t* errorIndex) {
#if AMPR_EMU_PACK_IO_COMPAT_DIAGNOSTICS
    AMPR_KLOGF("[AMPR_CALL] apr.resolveIdsSizes num=%u first=%s",
               (unsigned)num,
               (path && num && path[0]) ? path[0] : "(null)");
#endif
    AMPR_VLOGF("lk.apr.resolveIdsSizes enter paths=%p num=%u ids=%p sizes=%p errorIndex=%p",
"""
replace_once(APR_BRIDGE, apr_resolve_sizes_anchor, apr_resolve_sizes_insert)


# Keep hybrid directory descriptors native. Returning a synthetic 0x67xxxxxx FD
# for a directory that physically exists forces every libc/kernel consumer
# (closedir, fstat, lseek, getdents, internal descriptor validation) through our
# hooks. Some game/libc paths validate or consume the descriptor directly. Use
# the real directory FD as the public handle and retain only the overlay state
# internally. Purely virtual directories still use encoded virtual descriptors.

hybrid_lookup_anchor = """static uint32_t allocate_virtual_directory_locked(
    PackState& state, const char* path, uint16_t pathLength, int realFd,
"""
hybrid_lookup_insert = """static bool find_hybrid_directory_slot(PackState& state, int fd,
                                       uint32_t* outIndex,
                                       uint16_t* outGeneration) {
    if (fd < 0) return false;
    for (uint32_t index = 0;
         index < AMPR_EMU_PACK_VIRTUAL_DIRECTORY_SLOTS;
         ++index) {
        AmprLockGuard lock(state.directoryMutexes[index]);
        const VirtualDirectorySlot& slot = state.virtualDirectories[index];
        if (slot.active && slot.realFd == fd) {
            if (outIndex) *outIndex = index;
            if (outGeneration) *outGeneration = slot.generation;
            return true;
        }
    }
    return false;
}

static uint32_t allocate_virtual_directory_locked(
    PackState& state, const char* path, uint16_t pathLength, int realFd,
"""
replace_once(PACK, hybrid_lookup_anchor, hybrid_lookup_insert)

hybrid_return_anchor = """    const int fd = encode_virtual_directory_fd(
        slot, state.virtualDirectories[slot].generation);
    state.stats.directoryOpens.fetch_add(1, std::memory_order_relaxed);
    if (realFd >= 0) {
        state.stats.directoryHybridOpens.fetch_add(1, std::memory_order_relaxed);
    } else {
        state.stats.directoryVirtualOpens.fetch_add(1, std::memory_order_relaxed);
    }
#if AMPR_EMU_PACK_IO_LOG
    AMPR_LOGF("apr.pack.dir.open path=%s vfd=0x%x realFd=%d mode=%s range=%u..%u",
              normalized, (unsigned)fd, realFd,
              realFd >= 0 ? "hybrid" : "virtual", rangeBegin, rangeEnd);
#endif
    return fd;
"""
hybrid_return_insert = """    const int fd = realFd >= 0
        ? realFd
        : encode_virtual_directory_fd(
              slot, state.virtualDirectories[slot].generation);
    state.stats.directoryOpens.fetch_add(1, std::memory_order_relaxed);
    if (realFd >= 0) {
        state.stats.directoryHybridOpens.fetch_add(1, std::memory_order_relaxed);
    } else {
        state.stats.directoryVirtualOpens.fetch_add(1, std::memory_order_relaxed);
    }
#if AMPR_EMU_PACK_IO_COMPAT_DIAGNOSTICS
    AMPR_KLOGF("[AMPR_DIR] open.public path=%s fd=%d realfd=%d mode=%s slot=%u",
               normalized, fd, realFd,
               realFd >= 0 ? "hybrid-native-fd" : "virtual",
               slot);
#endif
#if AMPR_EMU_PACK_IO_LOG
    AMPR_LOGF("apr.pack.dir.open path=%s vfd=0x%x realFd=%d mode=%s range=%u..%u",
              normalized, (unsigned)fd, realFd,
              realFd >= 0 ? "hybrid-native-fd" : "virtual", rangeBegin, rangeEnd);
#endif
    return fd;
"""
replace_once(PACK, hybrid_return_anchor, hybrid_return_insert)

close_anchor = """int ampr_pack_try_close_fd(int fd, bool* handled) {
    if (handled) *handled = false;
#if !AMPR_EMU_PACK_ENABLE
    (void)fd;
    return SCE_KERNEL_ERROR_EBADF;
#else
    PackState& state = pack_state();
    uint32_t index = 0;
    uint16_t generation = 0;
    if (decode_virtual_directory_fd(fd, &index, &generation)) {
"""
close_insert = """int ampr_pack_try_close_fd(int fd, bool* handled) {
    if (handled) *handled = false;
#if !AMPR_EMU_PACK_ENABLE
    (void)fd;
    return SCE_KERNEL_ERROR_EBADF;
#else
    PackState& state = pack_state();
    uint32_t index = 0;
    uint16_t generation = 0;
    const bool hybridDirectory =
        find_hybrid_directory_slot(state, fd, &index, &generation);
    if (hybridDirectory ||
        decode_virtual_directory_fd(fd, &index, &generation)) {
"""
replace_once(PACK, close_anchor, close_insert)

fstat_anchor = """int ampr_pack_try_fstat_fd(int fd, SceKernelStat* stat, bool* handled) {
    if (handled) *handled = false;
#if !AMPR_EMU_PACK_ENABLE
    (void)fd; (void)stat;
    return SCE_KERNEL_ERROR_EBADF;
#else
    if (!stat) return SCE_KERNEL_ERROR_EFAULT;
    PackState& state = pack_state();
    uint32_t index = 0;
    uint16_t generation = 0;
    if (decode_virtual_directory_fd(fd, &index, &generation)) {
        if (handled) *handled = true;
"""
fstat_insert = """int ampr_pack_try_fstat_fd(int fd, SceKernelStat* stat, bool* handled) {
    if (handled) *handled = false;
#if !AMPR_EMU_PACK_ENABLE
    (void)fd; (void)stat;
    return SCE_KERNEL_ERROR_EBADF;
#else
    if (!stat) return SCE_KERNEL_ERROR_EFAULT;
    PackState& state = pack_state();
    uint32_t index = 0;
    uint16_t generation = 0;
    const bool hybridDirectory =
        find_hybrid_directory_slot(state, fd, &index, &generation);
    if (hybridDirectory ||
        decode_virtual_directory_fd(fd, &index, &generation)) {
        if (handled) *handled = true;
"""
replace_once(PACK, fstat_anchor, fstat_insert)

dirread_anchor = """    uint32_t index = 0;
    uint16_t generation = 0;
    if (!decode_virtual_directory_fd(fd, &index, &generation)) {
        return SCE_KERNEL_ERROR_EBADF;
    }
"""
dirread_insert = """    uint32_t index = 0;
    uint16_t generation = 0;
    PackState& state = pack_state();
    if (!find_hybrid_directory_slot(state, fd, &index, &generation) &&
        !decode_virtual_directory_fd(fd, &index, &generation)) {
        return SCE_KERNEL_ERROR_EBADF;
    }
"""
replace_once(PACK, dirread_anchor, dirread_insert)

# The original function declares state after descriptor decode; the replacement
# above declares it earlier.
dirread_state_anchor = """    PackState& state = pack_state();
    KernelGetdentsFn getdentsFn = real_getdents();
"""
dirread_state_insert = """    KernelGetdentsFn getdentsFn = real_getdents();
"""
replace_once(PACK, dirread_state_anchor, dirread_state_insert)

lseek_anchor = """off_t ampr_pack_try_lseek_fd(int fd, off_t offset, int whence,
                             bool* handled) {
    if (handled) *handled = false;
#if !AMPR_EMU_PACK_ENABLE
    (void)fd; (void)offset; (void)whence;
    return static_cast<off_t>(SCE_KERNEL_ERROR_EBADF);
#else
    PackState& state = pack_state();
    uint32_t index = 0;
    uint16_t generation = 0;
    if (decode_virtual_directory_fd(fd, &index, &generation)) {
        if (handled) *handled = true;
"""
lseek_insert = """off_t ampr_pack_try_lseek_fd(int fd, off_t offset, int whence,
                             bool* handled) {
    if (handled) *handled = false;
#if !AMPR_EMU_PACK_ENABLE
    (void)fd; (void)offset; (void)whence;
    return static_cast<off_t>(SCE_KERNEL_ERROR_EBADF);
#else
    PackState& state = pack_state();
    uint32_t index = 0;
    uint16_t generation = 0;
    const bool hybridDirectory =
        find_hybrid_directory_slot(state, fd, &index, &generation);
    if (hybridDirectory ||
        decode_virtual_directory_fd(fd, &index, &generation)) {
        if (handled) *handled = true;
"""
replace_once(PACK, lseek_anchor, lseek_insert)

isvdir_anchor = """    uint32_t slot = 0;
    uint16_t generation = 0;
    if (!decode_virtual_directory_fd(fd, &slot, &generation)) return false;
    PackState& state = pack_state();
"""
isvdir_insert = """    uint32_t slot = 0;
    uint16_t generation = 0;
    PackState& state = pack_state();
    if (!find_hybrid_directory_slot(state, fd, &slot, &generation) &&
        !decode_virtual_directory_fd(fd, &slot, &generation)) return false;
"""
replace_once(PACK, isvdir_anchor, isvdir_insert)


# APR loose-file reads use the native AIO backend independently from backing-pack
# reads. Mounted image filesystems can complete those AIO requests with an error
# or a short result even when ordinary pread succeeds. Retry only completed,
# non-cancelled physical-file reads synchronously after the AIO request has been
# deleted. Packed virtual FDs remain on the existing pack path.
reactor_include_anchor = """#include "ampr_emu_index.h"
#include "ampr_emu_kernel_memory.h"
"""
reactor_include_insert = """#include "ampr_emu_index.h"
#include "ampr_emu_kernel_file.h"
#include "ampr_emu_kernel_memory.h"
"""
replace_once(APR_REACTOR, reactor_include_anchor, reactor_include_insert)

reactor_helper_anchor = """static int apr_aio_result_to_sce(int64_t value) {
    if (value >= 0) return 0;
    const int rc = static_cast<int>(value);
    const uint32_t u = static_cast<uint32_t>(rc);
    if ((u & 0xFFFF0000u) == 0x80020000u) {
        return rc;
    }
    const int err = (value > -256) ? static_cast<int>(-value) : EIO;
    return ampr_sce_errno_from_posix(err);
}
"""
reactor_helper_insert = """static int apr_aio_result_to_sce(int64_t value) {
    if (value >= 0) return 0;
    const int rc = static_cast<int>(value);
    const uint32_t u = static_cast<uint32_t>(rc);
    if ((u & 0xFFFF0000u) == 0x80020000u) {
        return rc;
    }
    const int err = (value > -256) ? static_cast<int>(-value) : EIO;
    return ampr_sce_errno_from_posix(err);
}

static bool apr_physical_pread_exact(int fd, void* buffer,
                                     uint64_t length, uint64_t offset) {
    if (fd < 0 || !buffer ||
        offset > static_cast<uint64_t>((std::numeric_limits<off_t>::max)()) ||
        length > static_cast<uint64_t>(SIZE_MAX) ||
        length > static_cast<uint64_t>((std::numeric_limits<off_t>::max)()) - offset) {
        return false;
    }
    uint8_t* out = static_cast<uint8_t*>(buffer);
    uint64_t done = 0;
    while (done < length) {
        const uint64_t remaining = length - done;
        const size_t want = static_cast<size_t>(
            (std::min)(remaining, static_cast<uint64_t>(1024u * 1024u)));
        const ssize_t rc = ampr_real_physical_pread(
            fd, out + static_cast<size_t>(done), want,
            static_cast<off_t>(offset + done));
        if (rc <= 0 || static_cast<size_t>(rc) > want) {
            return false;
        }
        done += static_cast<uint64_t>(rc);
    }
    return true;
}
"""
replace_once(APR_REACTOR, reactor_helper_anchor, reactor_helper_insert)

short_anchor = """        const bool shortRead =
            finalState == SCE_KERNEL_AIO_STATE_COMPLETED &&
            active.result.returnValue >= 0 &&
            static_cast<uint64_t>(active.result.returnValue) != active.desc.length;
"""
short_insert = """        bool shortRead =
            finalState == SCE_KERNEL_AIO_STATE_COMPLETED &&
            active.result.returnValue >= 0 &&
            static_cast<uint64_t>(active.result.returnValue) != active.desc.length;
"""
replace_once(APR_REACTOR, short_anchor, short_insert)

fallback_anchor = """        if (!job || !chain) {
            apr_release_aio_read_desc(active.desc);
            decrement_active_read_count(job);
            decrement_read_chain_active(chain, active.readCreditBytes);
            maybe_finish_read_chain(chain);
            return false;
        }
#if AMPR_EMU_DEBUG_LOG
"""
fallback_insert = """        if (!job || !chain) {
            apr_release_aio_read_desc(active.desc);
            decrement_active_read_count(job);
            decrement_read_chain_active(chain, active.readCreditBytes);
            maybe_finish_read_chain(chain);
            return false;
        }

        const bool physicalAioCompatCandidate =
            finalState == SCE_KERNEL_AIO_STATE_COMPLETED &&
            rc != SCE_KERNEL_ERROR_EFAULT &&
            rc != SCE_KERNEL_ERROR_ECANCELED &&
            active.desc.fd >= 0 &&
            !ampr_pack_is_virtual_fd(active.desc.fd);
        if (physicalAioCompatCandidate) {
            const int originalRc = rc;
            const bool originalShortRead = shortRead;
            const int64_t originalReturn = active.result.returnValue;
            const bool refreshed = apr_physical_pread_exact(
                active.desc.fd,
                active.desc.buffer,
                active.desc.length,
                active.desc.offset);
            AMPR_KLOGF("[AMPR_APR_IO] physical-pread-refresh fileId=%u path=%s fd=%d len=0x%llx off=0x%llx aio_rc=0x%x aio_return=0x%llx short=%u refreshed=%u",
                       active.desc.fileId,
                       active.desc.filePath ? active.desc.filePath : "(null)",
                       active.desc.fd,
                       (unsigned long long)active.desc.length,
                       (unsigned long long)active.desc.offset,
                       originalRc,
                       (unsigned long long)originalReturn,
                       originalShortRead ? 1u : 0u,
                       refreshed ? 1u : 0u);
            if (refreshed) {
                rc = 0;
                shortRead = false;
                active.result.returnValue =
                    static_cast<int64_t>(active.desc.length);
            }
        }
#if AMPR_EMU_DEBUG_LOG
"""
replace_once(APR_REACTOR, fallback_anchor, fallback_insert)

# Report the exact APR resolve outcome in the same build, so one hardware run
# distinguishes resolver/index failure from a subsequent physical read failure.
resolve_done_anchor = """    const int rc = sce::Ampr::Emu::aprResolveFilepathsToIdsAndFileSizes(
        path, num, (SceAprFileId*)ids, fileSizes, effectiveErrorIndex);
    AMPR_VLOGF("lk.apr.resolveIdsSizes leave rc=0x%x ids=%p sizes=%p errorIndex=%p",
              rc, ids, fileSizes, errorIndex);
"""
resolve_done_insert = """    const int rc = sce::Ampr::Emu::aprResolveFilepathsToIdsAndFileSizes(
        path, num, (SceAprFileId*)ids, fileSizes, effectiveErrorIndex);
#if AMPR_EMU_PACK_IO_COMPAT_DIAGNOSTICS
    if (rc == 0 && num != 0 && ids && fileSizes) {
        AMPR_KLOGF("[AMPR_CALL] apr.resolveIdsSizes done rc=0 id0=%u size0=0x%llx",
                   ids[0], (unsigned long long)fileSizes[0]);
    } else {
        AMPR_KLOGF("[AMPR_CALL] apr.resolveIdsSizes done rc=0x%x errorIndex=%u",
                   rc,
                   effectiveErrorIndex ? *effectiveErrorIndex : UINT32_MAX);
    }
#endif
    AMPR_VLOGF("lk.apr.resolveIdsSizes leave rc=0x%x ids=%p sizes=%p errorIndex=%p",
              rc, ids, fileSizes, errorIndex);
"""
replace_once(APR_BRIDGE, resolve_done_anchor, resolve_done_insert)


# Trace the APR command-buffer path immediately after file resolution. This is
# diagnostic-only and uses the always-visible kernel log so a single run shows
# whether the game reaches measure/append/submit/wait before aborting.
apr_read_export_anchor = """extern "C" AMPR_EXPORT int64_t sceAmprAprCommandBufferReadFile(
        sce::Ampr::AprCommandBuffer* self,
        __SceAprMapState* mapState,
        __SceAprScatterGatherState* scatterGatherState,
        uint32_t fileId,
        void* buffer,
        uint64_t length,
        uint64_t offset) {
    ampr_export_vlogf("[apr-cb-30] sceAmprAprCommandBufferReadFile enter this=%p hiddenA2=%p hiddenA3=%p fileId=%u buffer=%p len=0x%llx off=0x%llx",
"""
apr_read_export_insert = """extern "C" AMPR_EXPORT int64_t sceAmprAprCommandBufferReadFile(
        sce::Ampr::AprCommandBuffer* self,
        __SceAprMapState* mapState,
        __SceAprScatterGatherState* scatterGatherState,
        uint32_t fileId,
        void* buffer,
        uint64_t length,
        uint64_t offset) {
#if AMPR_EMU_PACK_IO_COMPAT_DIAGNOSTICS
    AMPR_KLOGF("[AMPR_CALL] apr.cb.read enter fileId=%u len=0x%llx off=0x%llx buf=%p",
               fileId, (unsigned long long)length,
               (unsigned long long)offset, buffer);
#endif
    ampr_export_vlogf("[apr-cb-30] sceAmprAprCommandBufferReadFile enter this=%p hiddenA2=%p hiddenA3=%p fileId=%u buffer=%p len=0x%llx off=0x%llx",
"""
replace_once(EXPORTS, apr_read_export_anchor, apr_read_export_insert)

apr_read_leave_anchor = """    const int64_t rc = self->readFile((SceAprFileId)fileId, buffer, length, offset);
    const int64_t outRc = ampr_export_rc32(rc);
    ampr_export_vlogf("[apr-cb-31] sceAmprAprCommandBufferReadFile leave this=%p rc=0x%llx",
                     (void*)self, (unsigned long long)outRc);
    return outRc;
}
"""
apr_read_leave_insert = """    const int64_t rc = self->readFile((SceAprFileId)fileId, buffer, length, offset);
    const int64_t outRc = ampr_export_rc32(rc);
#if AMPR_EMU_PACK_IO_COMPAT_DIAGNOSTICS
    AMPR_KLOGF("[AMPR_CALL] apr.cb.read done fileId=%u rc=0x%llx",
               fileId, (unsigned long long)outRc);
#endif
    ampr_export_vlogf("[apr-cb-31] sceAmprAprCommandBufferReadFile leave this=%p rc=0x%llx",
                     (void*)self, (unsigned long long)outRc);
    return outRc;
}
"""
replace_once(EXPORTS, apr_read_leave_anchor, apr_read_leave_insert)

measure_read_anchor = """extern "C" AMPR_EXPORT int64_t sceAmprMeasureCommandSizeReadFile(SceAprFileId fileId, void* buffer, uint64_t length, uint64_t offset) {
    if (sce::Ampr::Emu::aprValidateReadArgs(buffer, length, offset) != 0) {
        return ampr_measure_einval();
    }
"""
measure_read_insert = """extern "C" AMPR_EXPORT int64_t sceAmprMeasureCommandSizeReadFile(SceAprFileId fileId, void* buffer, uint64_t length, uint64_t offset) {
#if AMPR_EMU_PACK_IO_COMPAT_DIAGNOSTICS
    AMPR_KLOGF("[AMPR_CALL] apr.measureRead fileId=%u len=0x%llx off=0x%llx buf=%p",
               (unsigned)fileId, (unsigned long long)length,
               (unsigned long long)offset, buffer);
#endif
    if (sce::Ampr::Emu::aprValidateReadArgs(buffer, length, offset) != 0) {
        return ampr_measure_einval();
    }
"""
replace_once(EXPORTS, measure_read_anchor, measure_read_insert)

submit_anchor = """extern "C" int sceKernelAprSubmitCommandBuffer_emul(sce::Ampr::AprCommandBuffer* commandBuffer, uint32_t prio) {
    return ampr_klog_io_hook_result(
        "sceKernelAprSubmitCommandBuffer",
        ampr_libkernel_return_from_sce(
            apr_submit_lowlevel_sce(commandBuffer, prio, nullptr, nullptr, AprSubmitMode::kSubmit, "submit")));
}
"""
submit_insert = """extern "C" int sceKernelAprSubmitCommandBuffer_emul(sce::Ampr::AprCommandBuffer* commandBuffer, uint32_t prio) {
#if AMPR_EMU_PACK_IO_COMPAT_DIAGNOSTICS
    AMPR_KLOGF("[AMPR_CALL] apr.submit enter cb=%p prio=%u", commandBuffer, (unsigned)prio);
#endif
    const int out = ampr_klog_io_hook_result(
        "sceKernelAprSubmitCommandBuffer",
        ampr_libkernel_return_from_sce(
            apr_submit_lowlevel_sce(commandBuffer, prio, nullptr, nullptr, AprSubmitMode::kSubmit, "submit")));
#if AMPR_EMU_PACK_IO_COMPAT_DIAGNOSTICS
    AMPR_KLOGF("[AMPR_CALL] apr.submit done rc=0x%x", out);
#endif
    return out;
}
"""
replace_once(APR_BRIDGE, submit_anchor, submit_insert)

submit_result_anchor = """extern "C" int sceKernelAprSubmitCommandBufferAndGetResult_emul(sce::Ampr::AprCommandBuffer* commandBuffer,
                                                                 uint32_t prio,
                                                                 SceAprResultBuffer* result,
                                                                 SceAprSubmitId* id) {
    return ampr_klog_io_hook_result(
        "sceKernelAprSubmitCommandBufferAndGetResult",
        ampr_libkernel_return_from_sce(
            apr_submit_lowlevel_sce(commandBuffer, prio, result, id, AprSubmitMode::kSubmitAndGetResult, "submit_result")));
}
"""
submit_result_insert = """extern "C" int sceKernelAprSubmitCommandBufferAndGetResult_emul(sce::Ampr::AprCommandBuffer* commandBuffer,
                                                                 uint32_t prio,
                                                                 SceAprResultBuffer* result,
                                                                 SceAprSubmitId* id) {
#if AMPR_EMU_PACK_IO_COMPAT_DIAGNOSTICS
    AMPR_KLOGF("[AMPR_CALL] apr.submitResult enter cb=%p prio=%u", commandBuffer, (unsigned)prio);
#endif
    const int out = ampr_klog_io_hook_result(
        "sceKernelAprSubmitCommandBufferAndGetResult",
        ampr_libkernel_return_from_sce(
            apr_submit_lowlevel_sce(commandBuffer, prio, result, id, AprSubmitMode::kSubmitAndGetResult, "submit_result")));
#if AMPR_EMU_PACK_IO_COMPAT_DIAGNOSTICS
    AMPR_KLOGF("[AMPR_CALL] apr.submitResult done rc=0x%x id=%u result=0x%x",
               out, id ? (unsigned)*id : 0u, result ? result->result : 0);
#endif
    return out;
}
"""
replace_once(APR_BRIDGE, submit_result_anchor, submit_result_insert)

submit_id_anchor = """extern "C" int sceKernelAprSubmitCommandBufferAndGetId_emul(sce::Ampr::AprCommandBuffer* commandBuffer,
                                                            uint32_t prio,
                                                            SceAprSubmitId* id) {
    return ampr_klog_io_hook_result(
        "sceKernelAprSubmitCommandBufferAndGetId",
        ampr_libkernel_return_from_sce(
            apr_submit_lowlevel_sce(commandBuffer, prio, nullptr, id, AprSubmitMode::kSubmitAndGetId, "submit_id")));
}
"""
submit_id_insert = """extern "C" int sceKernelAprSubmitCommandBufferAndGetId_emul(sce::Ampr::AprCommandBuffer* commandBuffer,
                                                            uint32_t prio,
                                                            SceAprSubmitId* id) {
#if AMPR_EMU_PACK_IO_COMPAT_DIAGNOSTICS
    AMPR_KLOGF("[AMPR_CALL] apr.submitId enter cb=%p prio=%u", commandBuffer, (unsigned)prio);
#endif
    const int out = ampr_klog_io_hook_result(
        "sceKernelAprSubmitCommandBufferAndGetId",
        ampr_libkernel_return_from_sce(
            apr_submit_lowlevel_sce(commandBuffer, prio, nullptr, id, AprSubmitMode::kSubmitAndGetId, "submit_id")));
#if AMPR_EMU_PACK_IO_COMPAT_DIAGNOSTICS
    AMPR_KLOGF("[AMPR_CALL] apr.submitId done rc=0x%x id=%u",
               out, id ? (unsigned)*id : 0u);
#endif
    return out;
}
"""
replace_once(APR_BRIDGE, submit_id_anchor, submit_id_insert)

wait_anchor = """extern "C" int sceKernelAprWaitCommandBuffer_emul(SceAprSubmitId id) {
    return ampr_klog_io_hook_result(
        "sceKernelAprWaitCommandBuffer",
        apr_wait_lowlevel(id,
                          kAmprLibkernelHook_sceKernelAprWaitCommandBuffer,
                          "apr-wait"));
}
"""
wait_insert = """extern "C" int sceKernelAprWaitCommandBuffer_emul(SceAprSubmitId id) {
#if AMPR_EMU_PACK_IO_COMPAT_DIAGNOSTICS
    AMPR_KLOGF("[AMPR_CALL] apr.wait enter id=%u", (unsigned)id);
#endif
    const int out = ampr_klog_io_hook_result(
        "sceKernelAprWaitCommandBuffer",
        apr_wait_lowlevel(id,
                          kAmprLibkernelHook_sceKernelAprWaitCommandBuffer,
                          "apr-wait"));
#if AMPR_EMU_PACK_IO_COMPAT_DIAGNOSTICS
    AMPR_KLOGF("[AMPR_CALL] apr.wait done id=%u rc=0x%x", (unsigned)id, out);
#endif
    return out;
}
"""
replace_once(APR_BRIDGE, wait_anchor, wait_insert)


# Result buffers are asynchronous outputs. Initialize accepted submissions to a
# deterministic success value before handing ownership to the reactor; final
# command/infrastructure failures still overwrite the buffer before wait
# completion is published. This avoids leaking caller stack garbage through a
# successful submit/wait sequence if a title inspects the buffer aggressively.
result_init_anchor = """    // Recording/mutation and object-lifetime isolation belong to the
    // application. Each caller snapshots the immutable stream independently;
    // the fixed reactor job owns everything needed after this call returns.
    const uint32_t logicalCommands = static_cast<uint32_t>(rawCommandCount);

    const uint64_t sid = apr_next_submit_id();
"""
result_init_insert = """    // Recording/mutation and object-lifetime isolation belong to the
    // application. Each caller snapshots the immutable stream independently;
    // the fixed reactor job owns everything needed after this call returns.
    const uint32_t logicalCommands = static_cast<uint32_t>(rawCommandCount);

    if (res) {
        res->result = 0;
        res->errorOffset = 0;
        std::atomic_thread_fence(std::memory_order_seq_cst);
#if AMPR_EMU_PACK_IO_COMPAT_DIAGNOSTICS
        AMPR_KLOGF("[AMPR_CALL] apr.result.init res=%p result=0 errorOffset=0", res);
#endif
    }

    const uint64_t sid = apr_next_submit_id();
"""
replace_once(APR_SERVICES, result_init_anchor, result_init_insert)

# Publish the final result value to the always-visible log immediately before
# signaling the synthetic waiter. This lets one run prove whether wait observes
# a successful result while also exercising the physical pread refresh.
publish_result_anchor = """        job.aprRes->result = result;
        job.aprRes->errorOffset = errorOffset;
        std::atomic_thread_fence(std::memory_order_seq_cst);
        AMPR_TLOGF("apr.reactor.result job=0x%llx mode=%s result=0x%x errorOffset=0x%x commandError=%u res=%p",
"""
publish_result_insert = """        job.aprRes->result = result;
        job.aprRes->errorOffset = errorOffset;
        std::atomic_thread_fence(std::memory_order_seq_cst);
#if AMPR_EMU_PACK_IO_COMPAT_DIAGNOSTICS
        AMPR_KLOGF("[AMPR_CALL] apr.result.final job=0x%llx result=0x%x errorOffset=0x%x commandError=%u res=%p",
                   (unsigned long long)job.id,
                   result,
                   errorOffset,
                   job.hasCommandError ? 1u : 0u,
                   job.aprRes);
#endif
        AMPR_TLOGF("apr.reactor.result job=0x%llx mode=%s result=0x%x errorOffset=0x%x commandError=%u res=%p",
"""
replace_once(APR_REACTOR, publish_result_anchor, publish_result_insert)


# If the mounted filesystem rejects native AIO submission entirely, recover
# physical APR reads synchronously instead of translating the backend failure to
# APR_UNAVAILABLEFILEID. This path runs only for non-deferred submit failures,
# preserves packed/virtual reads, and commits the same ReadChain accounting that
# accept_aio_submit_item() would have committed before an asynchronous completion.
reject_anchor = """        active->awaitingBatchSubmit = false;
        rollback_staged_aio_admission(*admission, *active);
        apr_release_aio_read_desc(active->desc);
        decrement_active_read_count(job);
        decrement_read_chain_active(chain, active->readCreditBytes);
        (void)erase_active_read(activeReads.iterator_from_slot(item.slot));
        detach_staged_read_chain(job, chain);
        chain->allIssued = true;
        maybe_finish_read_chain(chain);
        if (!job_failed(*job)) {
            set_or_defer_read_command_error(
                *job,
                "aio-submit",
                apr_backend_read_error_to_apr(submitSceRc),
                errorOff);
        }
        maybe_release_reactor_job(job);
"""
reject_insert = """        active->awaitingBatchSubmit = false;
        rollback_staged_aio_admission(*admission, *active);

        const bool physicalSyncCandidate =
            active->desc.fd >= 0 &&
            !ampr_pack_is_virtual_fd(active->desc.fd);
        if (physicalSyncCandidate) {
            const bool recovered = apr_physical_pread_exact(
                active->desc.fd,
                active->desc.buffer,
                active->desc.length,
                active->desc.offset);
            AMPR_KLOGF("[AMPR_APR_IO] aio-submit-sync-fallback fileId=%u path=%s fd=%d len=0x%llx off=0x%llx submitRc=0x%x recovered=%u",
                       active->desc.fileId,
                       active->desc.filePath ? active->desc.filePath : "(null)",
                       active->desc.fd,
                       (unsigned long long)active->desc.length,
                       (unsigned long long)active->desc.offset,
                       submitSceRc,
                       recovered ? 1u : 0u);
            if (recovered) {
                reserve_read_chain_sequence(*job, *chain);
                if (active->seq != chain->seq) {
                    AMPR_KLOGF("ampr.abort reason=apr.reactor.aio.submit.sync.sequence file=%s line=%d", __FILE__, __LINE__);
                    std::abort();
                }
                const uint64_t issuedLength = active->desc.length;
                if (issuedLength == 0 || issuedLength > chain->remaining) {
                    AMPR_KLOGF("ampr.abort reason=apr.reactor.aio.submit.sync.range file=%s line=%d", __FILE__, __LINE__);
                    std::abort();
                }
                chain->remaining -= issuedLength;
                chain->nextBuffer = reinterpret_cast<void*>(
                    reinterpret_cast<uintptr_t>(chain->nextBuffer) +
                    static_cast<uintptr_t>(issuedLength));
                chain->nextOffset += issuedLength;
                active->submitAccounted = true;

                apr_release_aio_read_desc(active->desc);
                decrement_active_read_count(job);
                decrement_read_chain_active(chain, active->readCreditBytes);
                (void)erase_active_read(activeReads.iterator_from_slot(item.slot));
                if (chain->remaining == 0) {
                    chain->allIssued = true;
                    detach_staged_read_chain(job, chain);
                }
                maybe_finish_read_chain(chain);
                maybe_release_reactor_job(job);
                return;
            }
        }

        apr_release_aio_read_desc(active->desc);
        decrement_active_read_count(job);
        decrement_read_chain_active(chain, active->readCreditBytes);
        (void)erase_active_read(activeReads.iterator_from_slot(item.slot));
        detach_staged_read_chain(job, chain);
        chain->allIssued = true;
        maybe_finish_read_chain(chain);
        if (!job_failed(*job)) {
            set_or_defer_read_command_error(
                *job,
                "aio-submit",
                apr_backend_read_error_to_apr(submitSceRc),
                errorOff);
        }
        maybe_release_reactor_job(job);
"""
replace_once(APR_REACTOR, reject_anchor, reject_insert)


# Mounted filesystems do not necessarily accept O_NONBLOCK on ordinary files.
# APR only needs a readable descriptor; async behavior comes from sceKernelAio*
# itself, not from the open flag. Use plain O_RDONLY for all physical APR file
# descriptors so loose files on ShadowMount/EXLZ can be opened before AIO or
# synchronous fallback is attempted.
aio_open_flags_anchor = """static constexpr int kAprAioOpenFlags = O_RDONLY | O_NONBLOCK;
"""
aio_open_flags_insert = """static constexpr int kAprAioOpenFlags = O_RDONLY;
"""
replace_once(APR_REACTOR, aio_open_flags_anchor, aio_open_flags_insert)

# Make the direct-open outcome visible even with normal AMPR debug logging off.
direct_open_anchor = """        int fd = ampr_real_posix_open(
            directEntry.path,
            kAprAioOpenFlags,
            static_cast<SceKernelMode>(0));
        if (fd == -1) fd = ampr_sce_errno_from_posix(errno);
"""
direct_open_insert = """        int fd = ampr_real_posix_open(
            directEntry.path,
            kAprAioOpenFlags,
            static_cast<SceKernelMode>(0));
        const int directOpenErrno = fd == -1 ? errno : 0;
        if (fd == -1) fd = ampr_sce_errno_from_posix(directOpenErrno);
#if AMPR_EMU_PACK_IO_COMPAT_DIAGNOSTICS
        AMPR_KLOGF("[AMPR_APR_IO] direct-open fileId=%u path=%s flags=0x%x fd=%d errno=%d",
                   rd.fileId,
                   directEntry.path ? directEntry.path : "(null)",
                   kAprAioOpenFlags,
                   fd,
                   directOpenErrno);
#endif
"""
replace_once(APR_REACTOR, direct_open_anchor, direct_open_insert)


# Compatibility path for small full-file APR reads on mounted filesystems.
# These reads do not benefit from FD-cache promotion and are especially
# sensitive to synthetic/mounted filesystem semantics. Force them onto the
# direct descriptor path, then complete them synchronously before native AIO.
policy_anchor = """static void apr_update_read_desc_fd_policy(AprAioReadDesc& rd,
                                           bool promoteFullFile) {
    if (!rd.fileMetadataValid) {
        return;
    }
    const bool fullFile = apr_read_is_single_quantum_full_file(
        rd.offset, rd.length, static_cast<uint64_t>(rd.fileSize));
    // Compatibility mode: full-file APR reads should not be diverted into the
    // shared FD cache merely because the adaptive policy promotes them. On
    // mounted/virtual filesystems this hides the physical open behind the cache
    // and bypasses the direct-open/AIO recovery path. Keep full-file reads on
    // the direct descriptor path; partial/streaming reads still use the cache.
    rd.bypassFdCache = fullFile;
    (void)promoteFullFile;
#if AMPR_EMU_PACK_IO_COMPAT_DIAGNOSTICS
    if (fullFile) {
        AMPR_KLOGF("[AMPR_APR_IO] full-file-direct fileId=%u size=0x%llx off=0x%llx len=0x%llx",
                   rd.fileId,
                   (unsigned long long)rd.fileSize,
                   (unsigned long long)rd.offset,
                   (unsigned long long)rd.length);
    }
#endif
}
"""
policy_insert = """static void apr_update_read_desc_fd_policy(AprAioReadDesc& rd,
                                           bool promoteFullFile) {
    (void)promoteFullFile;
    if (!rd.fileMetadataValid) {
        return;
    }
    rd.bypassFdCache = apr_read_is_single_quantum_full_file(
        rd.offset, rd.length, static_cast<uint64_t>(rd.fileSize));
}
"""
replace_once(APR_REACTOR, policy_anchor, policy_insert)

enum_anchor = """    enum class DirectReadSubmitResult : uint8_t {
        Pending,
        Staged,
        Failed,
    };
"""
enum_insert = """    enum class DirectReadSubmitResult : uint8_t {
        Pending,
        Staged,
        Completed,
        Failed,
    };
"""
replace_once(APR_REACTOR, enum_anchor, enum_insert)

sync_anchor = """        if (chain.ownerDesc.fd < 0) {
            int acquireRc = 0;
            uint32_t acquireErrorOff = chain.ownerDesc.errorOff;
            const bool allowNewFd = !admission.fdPressure;
            const bool acquired = apr_acquire_aio_read_desc(job->id,
                                                            chain.ownerDesc,
                                                            allowNewFd,
                                                            admission.directFdCap,
                                                            &acquireRc,
                                                            &acquireErrorOff);
            if (!acquired) {
                if (apr_fd_acquire_sce_rc_is_deferred(acquireRc)) {
                    const uint64_t failureNowNs = time_counter_now();
                    if (acquireRc == SCE_KERNEL_ERROR_EMFILE) {
                        note_emfile_event();
                    }
                    if (fd_pressure_active(failureNowNs)) {
                        admission.current = false;
                    }
                    chain.retryNotBeforeNs =
                        failureNowNs + AMPR_EMU_APR_AIO_SUBMIT_RETRY_DELAY_NS;
                    return {DirectReadSubmitResult::Pending, nullptr, 0, 0};
                }
                chain.allIssued = true;
                const int aprRc = apr_backend_read_error_to_apr(acquireRc);
                const char* const errorReason =
                    apr_backend_read_error_reason("aio-acquire-fd", acquireRc);
                AMPR_CRITICAL_LOGF("apr.reactor.acquire.error-map job=0x%llx fileId=%u reason=%s backendRc=0x%x aprRc=0x%x errorOffset=0x%x",
                                   (unsigned long long)job->id,
                                   chain.ownerDesc.fileId,
                                   errorReason,
                                   acquireRc,
                                   aprRc,
                                   acquireErrorOff);
                return {DirectReadSubmitResult::Failed,
                        errorReason,
                        aprRc,
                        acquireErrorOff,
                        acquireRc};
            }
            // Rebuild after acquiring the chain-owned fd; the active slice
            // borrows this descriptor and never owns/duplicates the pin.
            sliceDesc = read_chain_next_desc(chain);
        }

        borrow_read_chain_fd(chain, sliceDesc);
"""
sync_insert = """        if (chain.ownerDesc.fd < 0) {
            int acquireRc = 0;
            uint32_t acquireErrorOff = chain.ownerDesc.errorOff;
            const bool allowNewFd = !admission.fdPressure;
            const bool acquired = apr_acquire_aio_read_desc(job->id,
                                                            chain.ownerDesc,
                                                            allowNewFd,
                                                            admission.directFdCap,
                                                            &acquireRc,
                                                            &acquireErrorOff);
            if (!acquired) {
                if (apr_fd_acquire_sce_rc_is_deferred(acquireRc)) {
                    const uint64_t failureNowNs = time_counter_now();
                    if (acquireRc == SCE_KERNEL_ERROR_EMFILE) {
                        note_emfile_event();
                    }
                    if (fd_pressure_active(failureNowNs)) {
                        admission.current = false;
                    }
                    chain.retryNotBeforeNs =
                        failureNowNs + AMPR_EMU_APR_AIO_SUBMIT_RETRY_DELAY_NS;
                    return {DirectReadSubmitResult::Pending, nullptr, 0, 0};
                }
                chain.allIssued = true;
                const int aprRc = apr_backend_read_error_to_apr(acquireRc);
                const char* const errorReason =
                    apr_backend_read_error_reason("aio-acquire-fd", acquireRc);
                AMPR_KLOGF("[AMPR_APR_IO] acquire-fail fileId=%u path=%s backendRc=0x%x aprRc=0x%x",
                           chain.ownerDesc.fileId,
                           chain.ownerDesc.filePath ? chain.ownerDesc.filePath : "(null)",
                           acquireRc,
                           aprRc);
                return {DirectReadSubmitResult::Failed,
                        errorReason,
                        aprRc,
                        acquireErrorOff,
                        acquireRc};
            }
            sliceDesc = read_chain_next_desc(chain);
        }

        const bool fullFileSyncCompat =
            chain.activeCount == 0u &&
            sliceDesc.offset == 0 &&
            sliceDesc.length == static_cast<uint64_t>(sliceDesc.fileSize) &&
            sliceDesc.length <= static_cast<uint64_t>(kSoftwareReadChunkMax) &&
            chain.remaining == sliceDesc.length;
        if (fullFileSyncCompat) {
            bool recovered = false;
            ssize_t syncRc = -1;
#if AMPR_EMU_PACK_ENABLE
            if (ampr_pack_is_virtual_fd(chain.ownerDesc.fd)) {
                bool handled = false;
                syncRc = ampr_pack_try_pread_fd(
                    chain.ownerDesc.fd,
                    sliceDesc.buffer,
                    static_cast<size_t>(sliceDesc.length),
                    static_cast<off_t>(sliceDesc.offset),
                    &handled);
                recovered = handled &&
                    syncRc == static_cast<ssize_t>(sliceDesc.length);
            } else
#endif
            {
                recovered = apr_physical_pread_exact(
                    chain.ownerDesc.fd,
                    sliceDesc.buffer,
                    sliceDesc.length,
                    sliceDesc.offset);
                syncRc = recovered
                    ? static_cast<ssize_t>(sliceDesc.length)
                    : static_cast<ssize_t>(-1);
            }

            AMPR_KLOGF("[AMPR_APR_IO] full-file-sync fileId=%u path=%s fd=%d virtual=%u len=0x%llx rc=%lld recovered=%u",
                       sliceDesc.fileId,
                       sliceDesc.filePath ? sliceDesc.filePath : "(null)",
                       chain.ownerDesc.fd,
                       ampr_pack_is_virtual_fd(chain.ownerDesc.fd) ? 1u : 0u,
                       (unsigned long long)sliceDesc.length,
                       (long long)syncRc,
                       recovered ? 1u : 0u);

            if (recovered) {
                reserve_read_chain_sequence(*job, chain);
                chain.remaining = 0;
                chain.nextBuffer = reinterpret_cast<void*>(
                    reinterpret_cast<uintptr_t>(chain.nextBuffer) +
                    static_cast<uintptr_t>(sliceDesc.length));
                chain.nextOffset += sliceDesc.length;
                return {DirectReadSubmitResult::Completed, nullptr, 0, 0};
            }
        }

        borrow_read_chain_fd(chain, sliceDesc);
"""
replace_once(APR_REACTOR, sync_anchor, sync_insert)

caller_anchor = """        if (outcome.result == DirectReadSubmitResult::Staged) {
"""
caller_insert = """        if (outcome.result == DirectReadSubmitResult::Completed) {
            if (chain->remaining != 0 || chain->activeCount != 0u ||
                chain->seq == 0 || !chain->hasPendingFinalGs) {
                AMPR_KLOGF("ampr.abort reason=apr.reactor.readChain.commitSync.invalid file=%s line=%d", __FILE__, __LINE__);
                std::abort();
            }
            chain->allIssued = true;
            chainSlot = nullptr;
            gs = chain->pendingFinalGs;
            if (advanceSource) {
                clear_cursor_read_wait_hint(job->prioIndex);
                advance_job_source_commands(
                    *job, opBytes, sourceCommandCount);
            }
            if (outLogicalIssued) {
                *outLogicalIssued = true;
            }
            maybe_finish_read_chain(chain);
            return true;
        }

        if (outcome.result == DirectReadSubmitResult::Staged) {
"""
replace_once(APR_REACTOR, caller_anchor, caller_insert)

print("Applied direct synchronous compatibility path for small full-file APR reads")

print("Applied APR physical-open compatibility for mounted filesystems")

print("Applied synchronous APR recovery for native AIO submit rejection")

print("Applied deterministic APR result init + authoritative physical pread refresh")

print("Applied APR command-buffer transition diagnostics")

print("Applied exhaustive AMPR diagnostics + APR physical AIO pread fallback")












