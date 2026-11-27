import asyncio
import random
import uuid
from datetime import datetime
from typing import Awaitable, Callable, Optional

from backend.ig_service import InstagramRateLimitError, InstagramService
from backend.models import (
    AllCleanRequest,
    DeleteStoriesRequest,
    DeleteThreadsRequest,
    JobStatusResponse,
    LogEntry,
    UnsendMessagesRequest,
)


class JobManager:
    """Runs bulk deletion tasks asynchronously with anti-ban delays and pause/resume/stop."""

    def __init__(self, ig_service: InstagramService) -> None:
        self.ig = ig_service
        self._task: Optional[asyncio.Task] = None
        self._pause_event = asyncio.Event()
        self._pause_event.set()
        self._stop_requested = False

        self.state = JobStatusResponse()

    def _log(self, level: str, message: str) -> None:
        entry = LogEntry(
            time=datetime.now().strftime("%H:%M:%S"),
            level=level,  # type: ignore[arg-type]
            message=message,
        )
        self.state.logs.append(entry)
        if len(self.state.logs) > 250:
            self.state.logs = self.state.logs[-250:]

    def is_active(self) -> bool:
        return self.state.status in ("running", "paused")

    def get_status(self) -> JobStatusResponse:
        return self.state

    def pause(self) -> JobStatusResponse:
        if self.state.status == "running":
            self._pause_event.clear()
            self.state.status = "paused"
            self._log("warn", "İşlem kullanıcı tarafından duraklatıldı.")
        return self.state

    def resume(self) -> JobStatusResponse:
        if self.state.status == "paused":
            self.state.status = "running"
            self._pause_event.set()
            self._log("info", "İşlem devam ettiriliyor...")
        return self.state

    def stop(self) -> JobStatusResponse:
        if self.is_active():
            self._stop_requested = True
            self._pause_event.set()
            self._log("warn", "Durdurma isteği alındı, güvenli şekilde sonlandırılıyor...")
        return self.state

    async def _sleep_safe(self, min_delay: float, max_delay: float, dry_run: bool) -> None:
        if dry_run or self.ig.demo_mode:
            delay = random.uniform(0.2, 0.45)
        else:
            lo = min(min_delay, max_delay)
            hi = max(min_delay, max_delay)
            delay = random.uniform(lo, hi)

        elapsed = 0.0
        step = 0.2
        while elapsed < delay:
            if self._stop_requested:
                return
            await self._pause_event.wait()
            chunk = min(step, delay - elapsed)
            await asyncio.sleep(chunk)
            elapsed += chunk

    def _start_job(
        self,
        job_type: str,
        dry_run: bool,
        runner: Callable[[], Awaitable[None]],
    ) -> JobStatusResponse:
        if self.is_active():
            raise RuntimeError("Şu anda devam eden bir temizlik görevi var. Önce bitmesini bekleyin veya durdurun.")

        self._stop_requested = False
        self._pause_event.set()
        self.state = JobStatusResponse(
            job_id=uuid.uuid4().hex[:10],
            job_type=job_type,
            status="running",
            dry_run=dry_run,
            total=0,
            processed=0,
            succeeded=0,
            failed=0,
            skipped=0,
            current_action="Hazırlanıyor...",
            logs=[],
        )

        async def _wrapper() -> None:
            try:
                await runner()
                if self._stop_requested:
                    self.state.status = "stopped"
                    self.state.current_action = "Kullanıcı tarafından durduruldu."
                    self._log("warn", "Görev durduruldu.")
                elif self.state.status == "running":
                    self.state.status = "completed"
                    self.state.current_action = "Tamamlandı."
                    self._log(
                        "success",
                        f"Görev tamamlandı! Başarılı: {self.state.succeeded}, Hatalı: {self.state.failed}, Atlanan: {self.state.skipped}",
                    )
            except InstagramRateLimitError as exc:
                self.state.status = "error"
                self.state.current_action = "Instagram hız sınırına (Rate Limit) takıldı."
                self._log(
                    "error",
                    f"Anti-Ban Koruması: Instagram hız sınırı algılandı, hesabınızı korumak için işlem durduruldu. ({exc})",
                )
            except Exception as exc:
                self.state.status = "error"
                self.state.current_action = f"Hata: {exc}"
                self._log("error", f"Beklenmeyen hata: {exc}")

        self._task = asyncio.create_task(_wrapper())
        return self.state

    # ------------------------------------------------------------------
    # Job 1: Delete DM Threads
    # ------------------------------------------------------------------
    def start_delete_threads(self, req: DeleteThreadsRequest) -> JobStatusResponse:
        async def _run() -> None:
            self.state.total = len(req.thread_ids)
            mode_tag = "[ÖNİZLEME] " if req.dry_run else ""
            self._log("info", f"{mode_tag}{len(req.thread_ids)} DM sohbeti için temizlik başlatıldı.")

            for idx, tid in enumerate(req.thread_ids, start=1):
                if self._stop_requested:
                    break
                await self._pause_event.wait()
                self.state.current_action = f"DM sohbeti işleniyor ({idx}/{self.state.total})..."

                try:
                    if req.unsend_my_messages_first:
                        my_ids = await asyncio.to_thread(self.ig.get_my_messages_in_thread, tid, 80)
                        for mid in my_ids:
                            if self._stop_requested:
                                break
                            await self._pause_event.wait()
                            if not req.dry_run:
                                await asyncio.to_thread(self.ig.unsend_message, tid, mid)
                                await self._sleep_safe(req.min_delay, req.max_delay, req.dry_run)
                        self._log("info", f"{mode_tag}Sohbet {tid}: {len(my_ids)} gönderilen mesaj geri alındı.")

                    if not req.dry_run:
                        await asyncio.to_thread(self.ig.delete_thread, tid)

                    self.state.succeeded += 1
                    self._log("success", f"{mode_tag}DM sohbeti silindi: {tid}")
                except InstagramRateLimitError:
                    raise
                except Exception as exc:
                    self.state.failed += 1
                    self._log("error", f"Sohbet silinemedi ({tid}): {exc}")

                self.state.processed += 1
                if idx < self.state.total:
                    await self._sleep_safe(req.min_delay, req.max_delay, req.dry_run)

        return self._start_job("delete_threads", req.dry_run, _run)

    # ------------------------------------------------------------------
    # Job 2: Unsend Matched Messages (Keyword Search)
    # ------------------------------------------------------------------
    def start_unsend_messages(self, req: UnsendMessagesRequest) -> JobStatusResponse:
        async def _run() -> None:
            self.state.total = len(req.items)
            mode_tag = "[ÖNİZLEME] " if req.dry_run else ""
            self._log("info", f"{mode_tag}{len(req.items)} mesaj geri alınıyor (Unsend)...")

            for idx, item in enumerate(req.items, start=1):
                if self._stop_requested:
                    break
                await self._pause_event.wait()
                snippet = (item.preview or item.message_id)[:45]
                self.state.current_action = f"Mesaj geri alınıyor ({idx}/{self.state.total}): {snippet}"

                try:
                    if not req.dry_run:
                        await asyncio.to_thread(self.ig.unsend_message, item.thread_id, item.message_id)
                    self.state.succeeded += 1
                    self._log("success", f"{mode_tag}Mesaj geri alındı: \"{snippet}\"")
                except InstagramRateLimitError:
                    raise
                except Exception as exc:
                    self.state.failed += 1
                    self._log("error", f"Mesaj geri alınamadı ({item.message_id}): {exc}")

                self.state.processed += 1
                if idx < self.state.total:
                    await self._sleep_safe(req.min_delay, req.max_delay, req.dry_run)

        return self._start_job("unsend_messages", req.dry_run, _run)

    # ------------------------------------------------------------------
    # Job 3: Delete Archived Stories
    # ------------------------------------------------------------------
    def start_delete_stories(self, req: DeleteStoriesRequest) -> JobStatusResponse:
        async def _run() -> None:
            self.state.total = len(req.items)
            mode_tag = "[ÖNİZLEME] " if req.dry_run else ""
            self._log("info", f"{mode_tag}{len(req.items)} arşivlenmiş hikaye siliniyor...")

            for idx, item in enumerate(req.items, start=1):
                if self._stop_requested:
                    break
                await self._pause_event.wait()
                self.state.current_action = f"Hikaye siliniyor ({idx}/{self.state.total})..."

                try:
                    if not req.dry_run:
                        await asyncio.to_thread(
                            self.ig.delete_archived_story, item.media_id, item.media_type
                        )
                    self.state.succeeded += 1
                    self._log("success", f"{mode_tag}Arşiv hikaye silindi ({item.media_type}): {item.media_id}")
                except InstagramRateLimitError:
                    raise
                except Exception as exc:
                    self.state.failed += 1
                    self._log("error", f"Hikaye silinemedi ({item.media_id}): {exc}")

                self.state.processed += 1
                if idx < self.state.total:
                    await self._sleep_safe(req.min_delay, req.max_delay, req.dry_run)

        return self._start_job("delete_stories", req.dry_run, _run)

    # ------------------------------------------------------------------
    # Job 4: ALL CLEAN (DM + Archived Stories)
    # ------------------------------------------------------------------
    def start_all_clean(self, req: AllCleanRequest) -> JobStatusResponse:
        async def _run() -> None:
            mode_tag = "[ÖNİZLEME] " if req.dry_run else ""
            self._log("info", f"{mode_tag}All Clean (Tam Temizlik) taraması başlatılıyor...")

            threads = []
            stories = []

            if req.delete_dm_threads:
                self.state.current_action = "DM sohbetleri taranıyor..."
                threads = await asyncio.to_thread(self.ig.get_threads, 100)
                self._log("info", f"{len(threads)} DM sohbeti bulundu.")

            if req.delete_archived_stories:
                self.state.current_action = "Arşivlenmiş hikayeler taranıyor..."
                stories = await asyncio.to_thread(self.ig.get_archived_stories, 200)
                self._log("info", f"{len(stories)} arşivlenmiş hikaye bulundu.")

            self.state.total = len(threads) + len(stories)
            if self.state.total == 0:
                self._log("info", "Temizlenecek DM veya arşiv hikaye bulunamadı.")
                return

            # 1) Clean DMs
            for idx, th in enumerate(threads, start=1):
                if self._stop_requested:
                    break
                await self._pause_event.wait()

                if req.respect_whitelist and th.is_whitelisted:
                    self.state.skipped += 1
                    self.state.processed += 1
                    self._log("warn", f"Koruma listesinde (Whitelist) olduğu için atlandı: {th.title}")
                    continue

                self.state.current_action = f"DM temizleniyor ({idx}/{len(threads)}): {th.title}"
                try:
                    if req.unsend_my_messages:
                        my_ids = await asyncio.to_thread(self.ig.get_my_messages_in_thread, th.thread_id, 80)
                        for mid in my_ids:
                            if self._stop_requested:
                                break
                            await self._pause_event.wait()
                            if not req.dry_run:
                                await asyncio.to_thread(self.ig.unsend_message, th.thread_id, mid)
                                await self._sleep_safe(req.min_delay, req.max_delay, req.dry_run)

                    if not req.dry_run:
                        await asyncio.to_thread(self.ig.delete_thread, th.thread_id)
                    self.state.succeeded += 1
                    self._log("success", f"{mode_tag}DM sohbeti silindi: {th.title}")
                except InstagramRateLimitError:
                    raise
                except Exception as exc:
                    self.state.failed += 1
                    self._log("error", f"DM silinemedi ({th.title}): {exc}")

                self.state.processed += 1
                await self._sleep_safe(req.min_delay, req.max_delay, req.dry_run)

            # 2) Clean Archived Stories
            for idx, st in enumerate(stories, start=1):
                if self._stop_requested:
                    break
                await self._pause_event.wait()
                self.state.current_action = f"Arşiv hikaye siliniyor ({idx}/{len(stories)})..."
                try:
                    if not req.dry_run:
                        await asyncio.to_thread(self.ig.delete_archived_story, st.media_id, st.media_type)
                    self.state.succeeded += 1
                    self._log("success", f"{mode_tag}Arşiv hikaye silindi: {st.media_id}")
                except InstagramRateLimitError:
                    raise
                except Exception as exc:
                    self.state.failed += 1
                    self._log("error", f"Hikaye silinemedi ({st.media_id}): {exc}")

                self.state.processed += 1
                if idx < len(stories):
                    await self._sleep_safe(req.min_delay, req.max_delay, req.dry_run)

        return self._start_job("all_clean", req.dry_run, _run)
