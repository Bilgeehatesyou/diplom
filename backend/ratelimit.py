"""
Нэвтрэлтийн brute-force хамгаалалт (санах ойд, нэг процесст).

  * IP + нэр тус бүрд: 5 минутад 5 буруу оролдлого → 5 минут түгжинэ
  * IP тус бүрд (олон нэр туршиж "spray" хийх): 5 минутад 20 буруу оролдлого → түгжинэ
  * Амжилттай нэвтрэхэд тухайн IP+нэрийн тоолуур цэвэрлэгдэнэ

Олон процесс/сервертэй production-д Redis зэрэг хуваалцсан хадгалалт шаардлагатай.
"""
import time
from collections import defaultdict, deque


class LoginLimiter:
    def __init__(self, per_user: int = 5, per_ip: int = 20, window_sec: int = 300, lockout_sec: int = 300):
        self.per_user, self.per_ip = per_user, per_ip
        self.window, self.lockout = window_sec, lockout_sec
        self._fails: dict[str, deque] = defaultdict(deque)
        self._locked_until: dict[str, float] = {}

    def _keys(self, ip: str, username: str) -> tuple[str, str]:
        return f"u:{ip}:{username.strip().lower()}", f"ip:{ip}"

    def _prune(self, key: str, now: float):
        q = self._fails[key]
        while q and now - q[0] > self.window:
            q.popleft()

    def retry_after(self, ip: str, username: str, now: float | None = None) -> int:
        """Түгжигдсэн бол хэдэн секундын дараа оролдож болохыг буцаана, үгүй бол 0."""
        now = time.monotonic() if now is None else now
        wait = max((self._locked_until.get(k, 0) - now) for k in self._keys(ip, username))
        return max(0, int(wait + 0.999))

    def fail(self, ip: str, username: str, now: float | None = None):
        now = time.monotonic() if now is None else now
        for key, limit in zip(self._keys(ip, username), (self.per_user, self.per_ip)):
            self._prune(key, now)
            self._fails[key].append(now)
            if len(self._fails[key]) >= limit:
                self._locked_until[key] = now + self.lockout
                self._fails[key].clear()

    def success(self, ip: str, username: str):
        user_key, _ = self._keys(ip, username)
        self._fails.pop(user_key, None)
        self._locked_until.pop(user_key, None)


login_limiter = LoginLimiter()
