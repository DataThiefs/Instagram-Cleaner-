import base64
import json
import urllib.parse
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Optional

from backend.models import (
    AuthStatusResponse,
    MessageMatchItem,
    StoryArchiveItem,
    ThreadItem,
)

DATA_DIR = Path(__file__).resolve().parent.parent / "data"
WHITELIST_FILE = DATA_DIR / "whitelist.json"
SESSION_FILE = DATA_DIR / "session.json"


class InstagramAuthError(Exception):
    def __init__(self, message: str, code: str = "AUTH_ERROR"):
        super().__init__(message)
        self.code = code


class InstagramRateLimitError(Exception):
    pass


def _make_svg_thumb(label: str, sublabel: str, color1: str, color2: str) -> str:
    svg = (
        f'<svg xmlns="http://www.w3.org/2000/svg" width="320" height="560" viewBox="0 0 320 560">'
        f'<defs><linearGradient id="g" x1="0" y1="0" x2="1" y2="1">'
        f'<stop offset="0%" stop-color="{color1}"/><stop offset="100%" stop-color="{color2}"/>'
        f"</linearGradient></defs>"
        f'<rect width="320" height="560" rx="24" fill="url(#g)"/>'
        f'<circle cx="160" cy="210" r="54" fill="rgba(255,255,255,0.16)"/>'
        f'<text x="160" y="222" text-anchor="middle" fill="#fff" font-family="sans-serif" font-size="36" font-weight="700">{label}</text>'
        f'<text x="160" y="320" text-anchor="middle" fill="rgba(255,255,255,0.92)" font-family="sans-serif" font-size="18" font-weight="600">{sublabel}</text>'
        f"</svg>"
    )
    encoded = base64.b64encode(svg.encode("utf-8")).decode("ascii")
    return f"data:image/svg+xml;base64,{encoded}"


class InstagramService:
    """Manages Instagram session (real via instagrapi or safe local Demo Mode)."""

    def __init__(self) -> None:
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        self.client: Any = None
        self.authenticated: bool = False
        self.demo_mode: bool = False
        self.username: Optional[str] = None
        self.full_name: Optional[str] = None
        self.user_id: Optional[str] = None
        self.profile_pic_url: Optional[str] = None

        self._whitelist: set[str] = self._load_whitelist()

        # In-memory demo datasets
        self._demo_threads: list[dict[str, Any]] = []
        self._demo_messages: dict[str, list[dict[str, Any]]] = {}
        self._demo_stories: list[dict[str, Any]] = []

    # ------------------------------------------------------------------
    # Whitelist persistence
    # ------------------------------------------------------------------
    def _load_whitelist(self) -> set[str]:
        if WHITELIST_FILE.exists():
            try:
                data = json.loads(WHITELIST_FILE.read_text(encoding="utf-8"))
                return {str(u).strip().lower().lstrip("@") for u in data if str(u).strip()}
            except Exception:
                return set()
        return set()

    def _save_whitelist(self) -> None:
        WHITELIST_FILE.write_text(
            json.dumps(sorted(self._whitelist), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    def get_whitelist(self) -> list[str]:
        return sorted(self._whitelist)

    def add_whitelist(self, username: str) -> list[str]:
        clean = username.strip().lower().lstrip("@")
        if clean:
            self._whitelist.add(clean)
            self._save_whitelist()
        return self.get_whitelist()

    def remove_whitelist(self, username: str) -> list[str]:
        clean = username.strip().lower().lstrip("@")
        self._whitelist.discard(clean)
        self._save_whitelist()
        return self.get_whitelist()

    def is_thread_whitelisted(self, usernames: list[str]) -> bool:
        return any(u.lower().lstrip("@") in self._whitelist for u in usernames)

    # ------------------------------------------------------------------
    # Auth Status & Logout
    # ------------------------------------------------------------------
    def get_status(self) -> AuthStatusResponse:
        return AuthStatusResponse(
            authenticated=self.authenticated,
            demo_mode=self.demo_mode,
            username=self.username,
            full_name=self.full_name,
            user_id=self.user_id,
            profile_pic_url=self.profile_pic_url,
        )

    def logout(self) -> None:
        self.client = None
        self.authenticated = False
        self.demo_mode = False
        self.username = None
        self.full_name = None
        self.user_id = None
        self.profile_pic_url = None
        if SESSION_FILE.exists():
            try:
                SESSION_FILE.unlink()
            except OSError:
                pass

    # ------------------------------------------------------------------
    # Demo Mode
    # ------------------------------------------------------------------
    def start_demo_mode(self) -> AuthStatusResponse:
        self.logout()
        self.authenticated = True
        self.demo_mode = True
        self.username = "demo_kullanici"
        self.full_name = "Demo Hesap (Güvenli Test)"
        self.user_id = "999000111"
        self.profile_pic_url = None
        self._seed_demo_data()
        return self.get_status()

    def _seed_demo_data(self) -> None:
        now = datetime.now(timezone.utc)
        self._demo_threads = [
            {
                "thread_id": "demo_t_1",
                "title": "ahmet_yilmaz",
                "usernames": ["ahmet_yilmaz"],
                "user_ids": ["1001"],
                "is_group": False,
                "last_message": "Kanka IBAN bilgisini gönderdim, kontrol eder misin?",
                "last_activity": (now - timedelta(hours=3)).isoformat(),
            },
            {
                "thread_id": "demo_t_2",
                "title": "zeynep.kaya",
                "usernames": ["zeynep.kaya"],
                "user_ids": ["1002"],
                "is_group": False,
                "last_message": "Ev adresini tekrar yazar mısın kargo için",
                "last_activity": (now - timedelta(days=2)).isoformat(),
            },
            {
                "thread_id": "demo_t_3",
                "title": "Üniversite Ekip Grubu",
                "usernames": ["mert.dev", "elif_tas", "can_ozturk"],
                "user_ids": ["1003", "1004", "1005"],
                "is_group": True,
                "last_message": "Yarınki toplantı linki ve şifre burada",
                "last_activity": (now - timedelta(days=5)).isoformat(),
            },
            {
                "thread_id": "demo_t_4",
                "title": "eski_magaza_destek",
                "usernames": ["eski_magaza_destek"],
                "user_ids": ["1006"],
                "is_group": False,
                "last_message": "Sipariş numaranız ve telefon bilginiz alındı.",
                "last_activity": (now - timedelta(days=45)).isoformat(),
            },
            {
                "thread_id": "demo_t_5",
                "title": "burak.foto",
                "usernames": ["burak.foto"],
                "user_ids": ["1007"],
                "is_group": False,
                "last_message": "Eski tatil fotoğraflarını drive'a attım.",
                "last_activity": (now - timedelta(days=120)).isoformat(),
            },
            {
                "thread_id": "demo_t_6",
                "title": "selin_design",
                "usernames": ["selin_design"],
                "user_ids": ["1008"],
                "is_group": False,
                "last_message": "Teşekkürler, görüşürüz!",
                "last_activity": (now - timedelta(days=240)).isoformat(),
            },
        ]

        self._demo_messages = {
            "demo_t_1": [
                {
                    "message_id": "m_101",
                    "text": "Selam Ahmet, IBAN numaram TR00 0000 1234 5678",
                    "timestamp": (now - timedelta(hours=5)).isoformat(),
                    "is_mine": True,
                    "item_type": "text",
                },
                {
                    "message_id": "m_102",
                    "text": "Tamamdır aldım, birazdan atıyorum.",
                    "timestamp": (now - timedelta(hours=4)).isoformat(),
                    "is_mine": False,
                    "item_type": "text",
                },
                {
                    "message_id": "m_103",
                    "text": "Kanka IBAN bilgisini gönderdim, kontrol eder misin?",
                    "timestamp": (now - timedelta(hours=3)).isoformat(),
                    "is_mine": True,
                    "item_type": "text",
                },
            ],
            "demo_t_2": [
                {
                    "message_id": "m_201",
                    "text": "Benim ev adresim Kadıköy Moda Caddesi No:14",
                    "timestamp": (now - timedelta(days=3)).isoformat(),
                    "is_mine": True,
                    "item_type": "text",
                },
                {
                    "message_id": "m_202",
                    "text": "Ev adresini tekrar yazar mısın kargo için",
                    "timestamp": (now - timedelta(days=2)).isoformat(),
                    "is_mine": False,
                    "item_type": "text",
                },
            ],
            "demo_t_3": [
                {
                    "message_id": "m_301",
                    "text": "Wi-Fi şifre: yaz2025! not alın",
                    "timestamp": (now - timedelta(days=6)).isoformat(),
                    "is_mine": True,
                    "item_type": "text",
                },
                {
                    "message_id": "m_302",
                    "text": "Yarınki toplantı linki ve şifre burada",
                    "timestamp": (now - timedelta(days=5)).isoformat(),
                    "is_mine": True,
                    "item_type": "text",
                },
            ],
            "demo_t_4": [
                {
                    "message_id": "m_401",
                    "text": "Merhaba, telefon numaram 0555 000 00 00 ve adres bilgilerim ekte.",
                    "timestamp": (now - timedelta(days=46)).isoformat(),
                    "is_mine": True,
                    "item_type": "text",
                },
            ],
            "demo_t_5": [
                {
                    "message_id": "m_501",
                    "text": "Eski fotoğrafları silebiliriz artık.",
                    "timestamp": (now - timedelta(days=121)).isoformat(),
                    "is_mine": True,
                    "item_type": "text",
                },
            ],
            "demo_t_6": [
                {
                    "message_id": "m_601",
                    "text": "Harika olmuş, eline sağlık!",
                    "timestamp": (now - timedelta(days=241)).isoformat(),
                    "is_mine": True,
                    "item_type": "text",
                },
            ],
        }

        palettes = [
            ("#833ab4", "#fd1d1d"),
            ("#405de6", "#5851db"),
            ("#e1306c", "#f77737"),
            ("#00b4db", "#0083b0"),
            ("#11998e", "#38ef7d"),
            ("#fc466b", "#3f5efb"),
        ]
        ages_days = [5, 18, 42, 95, 160, 210, 320, 410, 560, 740]
        self._demo_stories = []
        for idx, age in enumerate(ages_days, start=1):
            dt = now - timedelta(days=age)
            mtype = "VIDEO" if idx % 3 == 0 else "PHOTO"
            c1, c2 = palettes[idx % len(palettes)]
            date_label = dt.strftime("%d.%m.%Y")
            self._demo_stories.append(
                {
                    "media_id": f"demo_story_{idx}",
                    "pk": f"900000{idx}",
                    "taken_at": dt.isoformat(),
                    "taken_at_ts": int(dt.timestamp()),
                    "media_type": mtype,
                    "thumbnail_url": _make_svg_thumb(
                        "VID" if mtype == "VIDEO" else "IMG",
                        f"Story #{idx} • {date_label}",
                        c1,
                        c2,
                    ),
                    "caption": f"Arşiv Hikaye #{idx}",
                }
            )

    # ------------------------------------------------------------------
    # Real Instagram Auth (instagrapi)
    # ------------------------------------------------------------------
    def _create_client(self) -> Any:
        from instagrapi import Client

        cl = Client()
        cl.delay_range = [1, 3]
        return cl

    def login_by_sessionid(self, raw_sessionid: str) -> AuthStatusResponse:
        sessionid = urllib.parse.unquote(raw_sessionid.strip())
        if not sessionid:
            raise InstagramAuthError("Geçerli bir sessionid girin.", "INVALID_SESSION")

        cl = self._create_client()
        try:
            ok = cl.login_by_sessionid(sessionid)
            if not ok:
                raise InstagramAuthError(
                    "Session ID geçersiz veya süresi dolmuş. Tarayıcıdan yeni sessionid alın.",
                    "INVALID_SESSION",
                )
            info = cl.account_info()
            self.client = cl
            self.authenticated = True
            self.demo_mode = False
            self.username = getattr(info, "username", None) or cl.username
            self.full_name = getattr(info, "full_name", "") or ""
            self.user_id = str(cl.user_id)
            pic = getattr(info, "profile_pic_url", None)
            self.profile_pic_url = str(pic) if pic else None
            try:
                cl.dump_settings(SESSION_FILE)
            except Exception:
                pass
            return self.get_status()
        except InstagramAuthError:
            raise
        except Exception as exc:
            raise InstagramAuthError(
                f"Session ID ile giriş başarısız: {exc}",
                "SESSION_LOGIN_FAILED",
            ) from exc

    def login_by_credentials(
        self,
        username: str,
        password: str,
        verification_code: Optional[str] = None,
    ) -> AuthStatusResponse:
        from instagrapi.exceptions import (
            BadPassword,
            ChallengeRequired,
            PleaseWaitFewMinutes,
            TwoFactorRequired,
        )

        cl = self._create_client()
        try:
            cl.login(
                username.strip(),
                password,
                verification_code=(verification_code or "").strip(),
            )
            info = cl.account_info()
            self.client = cl
            self.authenticated = True
            self.demo_mode = False
            self.username = getattr(info, "username", None) or username.strip()
            self.full_name = getattr(info, "full_name", "") or ""
            self.user_id = str(cl.user_id)
            pic = getattr(info, "profile_pic_url", None)
            self.profile_pic_url = str(pic) if pic else None
            try:
                cl.dump_settings(SESSION_FILE)
            except Exception:
                pass
            return self.get_status()
        except TwoFactorRequired as exc:
            raise InstagramAuthError(
                "2FA (İki Faktörlü Doğrulama) kodu gerekiyor. Lütfen doğrulama kodunu girip tekrar deneyin.",
                "TWO_FACTOR_REQUIRED",
            ) from exc
        except ChallengeRequired as exc:
            raise InstagramAuthError(
                "Instagram güvenlik doğrulaması (Challenge) istedi. En güvenli yol olarak 'Session ID' sekmesinden giriş yapmanız önerilir.",
                "CHALLENGE_REQUIRED",
            ) from exc
        except BadPassword as exc:
            raise InstagramAuthError(
                "Kullanıcı adı veya şifre hatalı.",
                "BAD_PASSWORD",
            ) from exc
        except PleaseWaitFewMinutes as exc:
            raise InstagramAuthError(
                "Instagram geçici hız sınırına takıldı. Lütfen birkaç dakika bekleyip tekrar deneyin.",
                "RATE_LIMITED",
            ) from exc
        except Exception as exc:
            raise InstagramAuthError(f"Giriş başarısız: {exc}", "LOGIN_FAILED") from exc

    def _require_auth(self) -> None:
        if not self.authenticated:
            raise InstagramAuthError("Önce Instagram hesabınıza giriş yapmalısınız.", "NOT_AUTHENTICATED")

    def _check_rate_limit(self, exc: Exception) -> None:
        name = type(exc).__name__.lower()
        msg = str(exc).lower()
        if any(
            k in name or k in msg
            for k in ("pleasewait", "ratelimit", "feedback_required", "challenge", "loginrequired", "429")
        ):
            raise InstagramRateLimitError(str(exc)) from exc

    # ------------------------------------------------------------------
    # DM Threads & Keyword Search
    # ------------------------------------------------------------------
    def get_threads(self, amount: int = 40) -> list[ThreadItem]:
        self._require_auth()
        if self.demo_mode:
            result: list[ThreadItem] = []
            for t in self._demo_threads[:amount]:
                msgs = self._demo_messages.get(t["thread_id"], [])
                result.append(
                    ThreadItem(
                        thread_id=t["thread_id"],
                        title=t["title"],
                        usernames=t["usernames"],
                        user_ids=t["user_ids"],
                        is_group=t["is_group"],
                        last_message=t["last_message"],
                        last_activity=t["last_activity"],
                        message_count_hint=len(msgs),
                        is_whitelisted=self.is_thread_whitelisted(t["usernames"]),
                    )
                )
            return result

        try:
            raw_threads = self.client.direct_threads(amount=amount)
        except Exception as exc:
            self._check_rate_limit(exc)
            raise

        items: list[ThreadItem] = []
        for th in raw_threads:
            usernames = [getattr(u, "username", "") for u in (th.users or []) if getattr(u, "username", "")]
            user_ids = [str(getattr(u, "pk", "")) for u in (th.users or []) if getattr(u, "pk", "")]
            title = th.thread_title or (", ".join(usernames) if usernames else f"Sohbet {th.id}")
            last_msg = ""
            if getattr(th, "messages", None):
                first_msg = th.messages[0]
                last_msg = getattr(first_msg, "text", None) or f"[{getattr(first_msg, 'item_type', 'medya')}]"
            last_act = ""
            if getattr(th, "last_activity_at", None):
                dt = th.last_activity_at
                last_act = dt.isoformat() if hasattr(dt, "isoformat") else str(dt)

            items.append(
                ThreadItem(
                    thread_id=str(th.id),
                    title=title,
                    usernames=usernames,
                    user_ids=user_ids,
                    is_group=bool(getattr(th, "is_group", False)),
                    last_message=last_msg[:120],
                    last_activity=last_act,
                    message_count_hint=len(getattr(th, "messages", None) or []),
                    is_whitelisted=self.is_thread_whitelisted(usernames),
                )
            )
        return items

    def search_messages(
        self,
        keyword: str,
        thread_ids: Optional[list[str]] = None,
        limit_per_thread: int = 60,
        only_mine: bool = True,
        case_sensitive: bool = False,
    ) -> list[MessageMatchItem]:
        self._require_auth()
        needle = keyword if case_sensitive else keyword.lower()
        matches: list[MessageMatchItem] = []

        if self.demo_mode:
            target_threads = (
                [t for t in self._demo_threads if t["thread_id"] in thread_ids]
                if thread_ids
                else self._demo_threads
            )
            for t in target_threads:
                for m in self._demo_messages.get(t["thread_id"], [])[:limit_per_thread]:
                    if only_mine and not m.get("is_mine", False):
                        continue
                    text = m.get("text") or ""
                    haystack = text if case_sensitive else text.lower()
                    if needle in haystack:
                        matches.append(
                            MessageMatchItem(
                                thread_id=t["thread_id"],
                                thread_title=t["title"],
                                message_id=m["message_id"],
                                text=text,
                                timestamp=m["timestamp"],
                                is_mine=bool(m.get("is_mine", False)),
                                item_type=m.get("item_type", "text"),
                            )
                        )
            return matches

        threads = self.get_threads(amount=30)
        if thread_ids:
            id_set = set(thread_ids)
            threads = [t for t in threads if t.thread_id in id_set]

        for th in threads:
            try:
                msgs = self.client.direct_messages(th.thread_id, amount=limit_per_thread)
            except Exception as exc:
                self._check_rate_limit(exc)
                continue

            for m in msgs:
                text = getattr(m, "text", None) or ""
                if not text:
                    continue
                is_mine = str(getattr(m, "user_id", "")) == str(self.user_id)
                if only_mine and not is_mine:
                    continue
                haystack = text if case_sensitive else text.lower()
                if needle in haystack:
                    ts = getattr(m, "timestamp", None)
                    ts_str = ts.isoformat() if hasattr(ts, "isoformat") else str(ts or "")
                    matches.append(
                        MessageMatchItem(
                            thread_id=th.thread_id,
                            thread_title=th.title,
                            message_id=str(m.id),
                            text=text,
                            timestamp=ts_str,
                            is_mine=is_mine,
                            item_type=str(getattr(m, "item_type", "text")),
                        )
                    )
        return matches

    def get_my_messages_in_thread(self, thread_id: str, limit: int = 80) -> list[str]:
        self._require_auth()
        if self.demo_mode:
            return [
                m["message_id"]
                for m in self._demo_messages.get(thread_id, [])[:limit]
                if m.get("is_mine", False)
            ]
        try:
            msgs = self.client.direct_messages(thread_id, amount=limit)
        except Exception as exc:
            self._check_rate_limit(exc)
            raise
        return [
            str(m.id)
            for m in msgs
            if str(getattr(m, "user_id", "")) == str(self.user_id)
        ]

    def unsend_message(self, thread_id: str, message_id: str) -> bool:
        self._require_auth()
        if self.demo_mode:
            msgs = self._demo_messages.get(thread_id, [])
            before = len(msgs)
            self._demo_messages[thread_id] = [m for m in msgs if m["message_id"] != message_id]
            return len(self._demo_messages[thread_id]) < before

        try:
            return bool(self.client.direct_message_delete(thread_id, message_id))
        except Exception as exc:
            self._check_rate_limit(exc)
            raise

    def delete_thread(self, thread_id: str) -> bool:
        self._require_auth()
        if self.demo_mode:
            before = len(self._demo_threads)
            self._demo_threads = [t for t in self._demo_threads if t["thread_id"] != thread_id]
            self._demo_messages.pop(thread_id, None)
            return len(self._demo_threads) < before

        try:
            return bool(self.client.direct_thread_hide(thread_id))
        except Exception as exc:
            self._check_rate_limit(exc)
            raise

    # ------------------------------------------------------------------
    # Archived Stories
    # ------------------------------------------------------------------
    def get_archived_stories(self, limit: int = 100) -> list[StoryArchiveItem]:
        self._require_auth()
        if self.demo_mode:
            return [StoryArchiveItem(**s) for s in self._demo_stories[:limit]]

        stories: list[StoryArchiveItem] = []
        try:
            shells = self.client.private_request(
                "archive/reel/day_shells/",
                params={
                    "include_suggested_highlights": "false",
                    "is_in_archive_home": "true",
                    "include_cover": "0",
                },
            )
        except Exception as exc:
            self._check_rate_limit(exc)
            raise

        shell_items = shells.get("items", []) if isinstance(shells, dict) else []
        reel_ids: list[str] = []
        for item in shell_items:
            rid = item.get("id")
            if rid:
                reel_ids.append(str(rid))
            if len(reel_ids) >= limit:
                break

        # Fetch actual story items in batches of 15
        for i in range(0, len(reel_ids), 15):
            batch = reel_ids[i : i + 15]
            try:
                res = self.client.private_request(
                    "feed/reels_media/",
                    data={"reel_ids": batch},
                )
            except Exception as exc:
                self._check_rate_limit(exc)
                continue

            reels_map = res.get("reels", {}) if isinstance(res, dict) else {}
            reels_list = list(reels_map.values()) if isinstance(reels_map, dict) else res.get("reels_media", [])
            for reel in reels_list:
                for media in reel.get("items", []):
                    mid = str(media.get("id") or media.get("pk") or "")
                    pk = str(media.get("pk") or mid)
                    if not mid:
                        continue
                    ts = int(media.get("taken_at") or 0)
                    dt_str = (
                        datetime.fromtimestamp(ts, tz=timezone.utc).isoformat()
                        if ts
                        else ""
                    )
                    mtype_code = media.get("media_type", 1)
                    mtype = "VIDEO" if mtype_code == 2 else "PHOTO"
                    thumb = None
                    candidates = (media.get("image_versions2") or {}).get("candidates") or []
                    if candidates:
                        thumb = candidates[0].get("url")
                    caption_obj = media.get("caption")
                    caption_txt = caption_obj.get("text") if isinstance(caption_obj, dict) else None

                    stories.append(
                        StoryArchiveItem(
                            media_id=mid,
                            pk=pk,
                            taken_at=dt_str,
                            taken_at_ts=ts,
                            media_type=mtype,
                            thumbnail_url=thumb,
                            caption=caption_txt,
                        )
                    )
                    if len(stories) >= limit:
                        return stories

        stories.sort(key=lambda s: s.taken_at_ts, reverse=True)
        return stories

    def delete_archived_story(self, media_id: str, media_type: str = "PHOTO") -> bool:
        self._require_auth()
        if self.demo_mode:
            before = len(self._demo_stories)
            self._demo_stories = [s for s in self._demo_stories if s["media_id"] != media_id]
            return len(self._demo_stories) < before

        try:
            try:
                return bool(self.client.media_delete(media_id))
            except Exception:
                res = self.client.private_request(
                    f"media/{media_id}/delete/?media_type={media_type}",
                    data={"media_id": media_id},
                )
                return bool(res.get("did_delete", True)) if isinstance(res, dict) else True
        except Exception as exc:
            self._check_rate_limit(exc)
            raise
