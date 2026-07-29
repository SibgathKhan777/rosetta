from urllib.parse import urlparse

_PLATFORM_HOSTS = {
    "youtube": ("youtube.com", "youtu.be", "m.youtube.com"),
    "instagram": ("instagram.com", "www.instagram.com"),
    "tiktok": ("tiktok.com", "www.tiktok.com"),
    "twitter": ("twitter.com", "x.com", "www.twitter.com", "www.x.com"),
}


def detect_platform(url: str) -> str:
    host = (urlparse(url).hostname or "").lower()
    for platform, hosts in _PLATFORM_HOSTS.items():
        if any(host == h or host.endswith("." + h) for h in hosts):
            return platform
    return "other"
