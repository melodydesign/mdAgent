import os
import sys

# Санитайзер переменных NO_PROXY для предотвращения бага httpx с IPv6 адресами
for _var in ("NO_PROXY", "no_proxy"):
    if _var in os.environ and os.environ[_var]:
        os.environ[_var] = ",".join(
            [h.strip() for h in os.environ[_var].split(",") if not h.strip().startswith("::")]
        )

import asyncio
import json
import logging
from contextlib import asynccontextmanager
from pathlib import Path

# На Windows для работы Playwright (подпроцессов Chromium) необходим ProactorEventLoop
if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles

from backend.agent import Agent
from backend.config import HOST, PORT

# Настройка логирования
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger(__name__)

# Глобальный агент
agent = Agent()

# Активные WebSocket подключения
active_connections: list[WebSocket] = []
_is_starting_session: bool = False


async def broadcast_event(event: dict):
    """Отправляет событие всем подключённым WebSocket-клиентам."""
    message = json.dumps(event, ensure_ascii=False)
    disconnected = []
    for ws in active_connections:
        try:
            await ws.send_text(message)
        except Exception:
            disconnected.append(ws)
    for ws in disconnected:
        active_connections.remove(ws)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Lifecycle: инициализация при старте, cleanup при остановке."""
    logger.info("mdAgent сервер запускается...")
    agent.set_event_callback(broadcast_event)
    yield
    logger.info("mdAgent сервер останавливается...")
    await agent.shutdown()


app = FastAPI(title="mdAgent", version="1.0.0", lifespan=lifespan)

# Статические файлы фронтенда
FRONTEND_DIR = Path(__file__).parent.parent / "frontend"
FRONTEND_DIST = FRONTEND_DIR / "dist"

if FRONTEND_DIST.exists() and (FRONTEND_DIST / "assets").exists():
    app.mount("/assets", StaticFiles(directory=str(FRONTEND_DIST / "assets")), name="assets")

if FRONTEND_DIR.exists():
    app.mount("/static", StaticFiles(directory=str(FRONTEND_DIR)), name="static")


# ─────────────────────────── HTTP Routes ───────────────────────────

@app.get("/", response_class=HTMLResponse)
async def root():
    """Отдаём React SPA из dist или legacy index.html."""
    if FRONTEND_DIST.exists():
        dist_index = FRONTEND_DIST / "index.html"
        if dist_index.exists():
            return FileResponse(str(dist_index), media_type="text/html")
    index_path = FRONTEND_DIR / "index.html"
    if index_path.exists():
        return FileResponse(str(index_path), media_type="text/html")
    return HTMLResponse("<h1>mdAgent</h1><p>Frontend не найден.</p>")


@app.get("/api/chat/history")
async def get_chat_history():
    """Возвращает сохраненную историю активного диалога."""
    return {
        "messages": agent.chat_storage.get_messages(),
        "active_session": agent.chat_storage.get_active_session()
    }


@app.delete("/api/chat/history")
async def clear_chat_history():
    """Очищает историю диалога на сервере."""
    agent.chat_storage.clear()
    await broadcast_event({"type": "chat_cleared"})
    return {"ok": True}


@app.get("/api/chat/sessions")
async def list_chat_sessions():
    """Возвращает список всех сохраненных сессий диалогов."""
    return {
        "sessions": agent.chat_storage.list_sessions(),
        "active_session_id": agent.chat_storage.get_active_session_id()
    }


@app.post("/api/chat/sessions")
async def create_chat_session(payload: dict):
    """Создает новый диалог."""
    title = payload.get("title", "Новый диалог")
    email = payload.get("tilda_email", "")
    pwd = payload.get("tilda_password", "")
    sess = agent.chat_storage.create_session(title=title, tilda_email=email, tilda_password=pwd)
    await broadcast_event({
        "type": "session_switched",
        "session": sess,
        "session_id": sess["id"],
        "messages": sess.get("messages", [])
    })
    return {"session": sess, "sessions": agent.chat_storage.list_sessions()}


@app.post("/api/chat/sessions/{session_id}/select")
async def select_chat_session(session_id: str):
    """Выбирает активный диалог."""
    sess = agent.chat_storage.select_session(session_id)
    if sess:
        await broadcast_event({
            "type": "session_switched",
            "session": sess,
            "session_id": sess["id"],
            "messages": sess.get("messages", [])
        })
        return {"ok": True, "session": sess}
    return {"ok": False, "error": "Сессия не найдена"}


@app.put("/api/chat/sessions/{session_id}")
async def update_chat_session(session_id: str, payload: dict):
    """Обновляет название или индивидуальные логин/пароль Tilda для диалога."""
    sess = agent.chat_storage.update_session(
        session_id=session_id,
        title=payload.get("title"),
        tilda_email=payload.get("tilda_email"),
        tilda_password=payload.get("tilda_password")
    )
    if sess:
        await broadcast_event({"type": "sessions_updated", "sessions": agent.chat_storage.list_sessions()})
        return {"ok": True, "session": sess}
    return {"ok": False, "error": "Сессия не найдена"}


@app.delete("/api/chat/sessions/{session_id}")
async def delete_chat_session(session_id: str):
    """Удаляет выбранный диалог."""
    ok = agent.chat_storage.delete_session(session_id)
    active = agent.chat_storage.get_active_session()
    await broadcast_event({
        "type": "session_switched",
        "session": active,
        "session_id": active["id"],
        "messages": active.get("messages", [])
    })
    return {"ok": ok, "sessions": agent.chat_storage.list_sessions()}


@app.get("/api/status")
async def get_status():
    """Статус агента."""
    return await agent.get_status()


@app.get("/api/memory")
async def get_memory():
    """Список проверенных навыков и сценариев из памяти."""
    return {"playbooks": agent.memory.get_all()}


@app.get("/api/quota")
async def get_quota():
    """Текущий расход лимитов Gemini API и каскада."""
    if agent.gemini:
        return agent.gemini.get_quota_status()
    return {
        "rpm_limit": 15,
        "rpm_remaining": 15,
        "rpm_used": 0,
        "rpd_limit": 1500,
        "rpd_remaining": 1500,
        "rpd_used": 0,
        "reset_seconds": 0,
        "day_reset_seconds": 0,
        "model": "gemini-3.8-flash",
        "provider": "gemini",
        "cascade": [],
    }


@app.get("/api/settings")
async def get_settings():
    """Возвращает текущие настройки AI провайдеров, каскад и статус подключения."""
    return {
        "active_provider": agent.active_provider,
        "providers": [
            {
                "id": "gemini",
                "name": "Google Gemini (AI Studio)",
                "connected": agent.gemini is not None,
                "active_model": getattr(agent.gemini, "active_model", "gemini-3.8-flash") if agent.gemini else "gemini-3.8-flash",
                "cascade": agent.gemini.get_cascade_status() if agent.gemini else [],
            },
            {
                "id": "hydraai",
                "name": "HydraAI (GPT-5.6 Luna)",
                "connected": agent.hydra is not None,
                "model": getattr(agent.hydra, "model", "gpt-5.6-luna") if agent.hydra else "gpt-5.6-luna",
                "info": {
                    "speed": "87.07 TPS",
                    "context": "256 000 токенов",
                    "features": ["Vision", "Reasoning", "GPT-5.6 Architecture"],
                },
            },
        ],
    }


@app.post("/api/settings")
async def update_settings(body: dict):
    """Обновляет активного AI провайдера ('gemini' или 'hydraai')."""
    provider = body.get("provider")
    if not provider or provider not in ("gemini", "hydraai"):
        return {"ok": False, "error": "Недопустимый провайдер (выберите 'gemini' или 'hydraai')"}

    try:
        agent.set_provider(provider)
        status = await agent.get_status()
        await broadcast_event({"type": "status", **status})
        provider_name = "HydraAI (GPT-5.6 Luna)" if provider == "hydraai" else "Google Gemini (Каскад 3.8 → 3.0)"
        await broadcast_event({
            "type": "log",
            "level": "info",
            "message": f"Активный провайдер: {provider_name}",
        })
        return {"ok": True, "active_provider": agent.active_provider, "status": status}
    except Exception as e:
        return {"ok": False, "error": str(e)}


@app.post("/api/start")
async def start_agent():
    """Запускает агента (браузер + AI)."""
    await agent.initialize()
    return {"ok": True, "status": await agent.get_status()}



@app.post("/api/stop")
async def stop_agent():
    """Останавливает агента."""
    await agent.shutdown()
    return {"ok": True}


@app.post("/api/pause")
async def pause_agent():
    """Ставит агента на паузу."""
    await agent.pause()
    return {"ok": True, "status": await agent.get_status()}


@app.post("/api/resume")
async def resume_agent():
    """Возобновляет работу агента с паузы."""
    await agent.resume()
    return {"ok": True, "status": await agent.get_status()}


@app.post("/api/bring_to_front")
async def bring_browser_to_front():
    """Выводит окно Chromium на передний план рабочего стола."""
    await agent.browser.bring_to_front()
    return {"ok": True}


@app.post("/api/command")
async def send_command(body: dict):
    """Отправляет команду агенту (REST альтернатива WebSocket)."""
    message = body.get("message", "")
    if not message:
        return {"ok": False, "error": "Пустая команда"}
    results = await agent.process_command(message)
    return {"ok": True, "results": results}


# ─────────────────────────── WebSocket ───────────────────────────

@app.websocket("/ws")
async def websocket_endpoint(ws: WebSocket):
    """WebSocket для real-time связи с UI."""
    global _is_starting_session
    await ws.accept()
    active_connections.append(ws)
    logger.info(f"WebSocket подключён. Активных: {len(active_connections)}")

    # Отправляем текущий статус
    status = await agent.get_status()
    await ws.send_text(json.dumps({"type": "status", **status}, ensure_ascii=False))

    # Отправляем сохраненную историю диалога
    try:
        chat_msgs = agent.chat_storage.get_messages()
        await ws.send_text(json.dumps({
            "type": "chat_history",
            "messages": chat_msgs
        }, ensure_ascii=False))
    except Exception as e:
        logger.warning(f"Ошибка отправки истории чата: {e}")

    # Если браузер уже работает — сразу отдаем актуальный скриншот и активируем live-поток
    if agent.browser.is_running:
        try:
            await agent.browser.start_screencast()
            shot = await agent.browser.screenshot()
            if shot:
                await ws.send_text(json.dumps({"type": "screenshot", "image": shot}))
        except Exception as e:
            logger.warning(f"Не удалось отправить начальный снимок экрана: {e}")

    try:
        while True:
            data = await ws.receive_text()
            try:
                msg = json.loads(data)
            except json.JSONDecodeError:
                msg = {"action": "command", "message": data}

            action = msg.get("action", "command")

            match action:
                case "command":
                    message = msg.get("message", "")
                    image_base64 = msg.get("image", "")
                    if message or image_base64:
                        # Выполняем в фоне чтобы не блокировать WebSocket
                        asyncio.create_task(agent.process_command(message, user_image_base64=image_base64))

                case "select_session":
                    sid = msg.get("session_id", "")
                    sess = agent.chat_storage.select_session(sid)
                    if sess:
                        await broadcast_event({
                            "type": "session_switched",
                            "session": sess,
                            "session_id": sess["id"],
                            "messages": sess.get("messages", [])
                        })

                case "confirm_plan":
                    plan_id = msg.get("plan_id", "")
                    steps = msg.get("steps", [])
                    asyncio.create_task(agent.confirm_plan(plan_id, steps))

                case "cancel_plan":
                    plan_id = msg.get("plan_id", "")
                    asyncio.create_task(agent.cancel_plan(plan_id))

                case "start":
                    if _is_starting_session or agent.browser.is_running:
                        await broadcast_event({
                            "type": "log",
                            "level": "info",
                            "message": "Запуск сессии уже выполняется или браузер уже активен",
                        })
                        break

                    async def _safe_start():
                        global _is_starting_session
                        if _is_starting_session:
                            return
                        _is_starting_session = True
                        try:
                            await agent.initialize()
                        except Exception as e:
                            err_msg = str(e).strip() or type(e).__name__
                            await broadcast_event({
                                "type": "error",
                                "message": f"Ошибка запуска: {err_msg}",
                            })
                            await broadcast_event({
                                "type": "status",
                                **(await agent.get_status()),
                            })
                        finally:
                            _is_starting_session = False
                    asyncio.create_task(_safe_start())

                case "stop":
                    _is_starting_session = False
                    asyncio.create_task(agent.shutdown())

                case "pause":
                    asyncio.create_task(agent.pause())

                case "resume":
                    asyncio.create_task(agent.resume())

                case "clear_chat":
                    agent.chat_storage.clear()
                    await broadcast_event({"type": "chat_cleared"})

                case "browser_input":
                    asyncio.create_task(agent.browser.handle_user_input(msg))

                case "bring_to_front":
                    asyncio.create_task(agent.browser.bring_to_front())

                case "screenshot":
                    if agent.browser.is_running:
                        screenshot = await agent.browser.screenshot()
                        try:
                            await ws.send_text(json.dumps({
                                "type": "screenshot",
                                "image": screenshot,
                            }))
                        except Exception:
                            pass

                case "status":
                    status = await agent.get_status()
                    try:
                        await ws.send_text(json.dumps({
                            "type": "status",
                            **status,
                        }, ensure_ascii=False))
                    except Exception:
                        pass

                case _:
                    try:
                        await ws.send_text(json.dumps({
                            "type": "error",
                            "message": f"Неизвестное действие: {action}",
                        }))
                    except Exception:
                        pass

    except WebSocketDisconnect:
        logger.info("WebSocket отключён")
    except Exception as e:
        logger.error(f"WebSocket ошибка: {e}")
    finally:
        if ws in active_connections:
            active_connections.remove(ws)
        logger.info(f"Активных подключений: {len(active_connections)}")


# ─────────────────────────── Entry point ───────────────────────────

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        "backend.main:app",
        host=HOST,
        port=PORT,
        reload=False,
        log_level="info",
    )
