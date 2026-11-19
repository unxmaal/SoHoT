// Loaded into monit (#2072): refuses any kill() aimed at pid <= 1, which monit 6.0.0 sends when a fork or pipe fails.
#include <errno.h>
#include <fcntl.h>
#include <signal.h>
#include <stdio.h>
#include <stdlib.h>
#include <unistd.h>

static int guarded_kill(pid_t pid, int sig) {
    if (pid <= 1) {
        char b[96];
        int n = snprintf(b, sizeof b, "monit-guard: refused kill(%d, %d) from pid %d\n", (int)pid, sig, (int)getpid());
        if (n > 0)
            (void)!write(2, b, (size_t)n);
        errno = EPERM;
        return -1;
    }
    return kill(pid, sig);
}

__attribute__((used, section("__DATA,__interpose"))) static const struct {
    const void *with;
    const void *what;
} interpose[] = {{(const void *)guarded_kill, (const void *)kill}};

__attribute__((constructor)) static void loaded(void) {
    const char *probe = getenv("MONIT_GUARD_PROBE");
    if (probe) {
        int fd = open(probe, O_WRONLY | O_CREAT | O_TRUNC, 0600);
        if (fd >= 0) {
            char b[24];
            int n = snprintf(b, sizeof b, "%d\n", (int)getpid());
            if (n > 0)
                (void)!write(fd, b, (size_t)n);
            close(fd);
        }
        unsetenv("MONIT_GUARD_PROBE");
    }
    unsetenv("DYLD_INSERT_LIBRARIES");
}
