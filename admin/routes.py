from pathlib import Path
from urllib.parse import quote

from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import HTMLResponse, RedirectResponse, Response
from fastapi.templating import Jinja2Templates
from sqlmodel import Session

from admin import db, repo, sync
from admin.models import HERO_CLASSES, LANES, TIERS, Hero

templates = Jinja2Templates(directory=Path(__file__).parent / "templates")

CLASS_COLORS = {
    "坦克": "#3f6fb5",
    "戰士": "#b5652a",
    "刺客": "#7b45b0",
    "法師": "#1f8fa3",
    "射手": "#b53d3d",
    "輔助": "#3a8a52",
}


def avatar_url(hero: Hero) -> str | None:
    mtime = repo.avatar_mtime(hero)
    if mtime is None:
        return None
    return f"/avatars/{quote(hero.avatar)}?v={mtime}"


def class_label(hero: Hero) -> str:
    main = hero.main_class or "未設定"
    return f"{main}/{hero.sub_class}" if hero.sub_class else main


templates.env.globals.update(
    avatar_url=avatar_url,
    class_label=class_label,
    CLASS_COLORS=CLASS_COLORS,
    HERO_CLASSES=HERO_CLASSES,
    LANES=LANES,
    TIERS=TIERS,
)

router = APIRouter(prefix="/admin")


# ---------------------------------------------------------------- plumbing


def get_session(request: Request):
    with sync.lock:
        with db.new_session() as session:
            try:
                imported = sync.check(session)
            except sync.SyncError:
                if request.method != "GET":
                    raise HTTPException(409, sync.status.error)
                imported = False
            if imported and request.headers.get("HX-Request"):
                # Ids or values on the open page may be stale: reload it.
                raise HTTPException(
                    409,
                    "偵測到 data.json 已更新（例如 git pull），已重新載入資料，頁面將重新整理。",
                    headers={"HX-Refresh": "true"},
                )
            yield session


SessionDep = Depends(get_session)


def save(session: Session) -> None:
    """Commit and re-export data.json so git always reflects the database."""
    session.commit()
    sync.export_to_disk(session)


def is_htmx(request: Request) -> bool:
    return bool(request.headers.get("HX-Request")) and not request.headers.get("HX-Boosted")


def render(request: Request, name: str, ctx: dict, *, trigger: str | None = None, status_code: int = 200):
    if name == "index.html":
        ctx = {**ctx, "sync_status": sync.status, "imported_notice": sync.status.imported_notice}
        sync.status.imported_notice = False
    resp = templates.TemplateResponse(request, name, ctx, status_code=status_code)
    if trigger:
        resp.headers["HX-Trigger"] = trigger
    return resp


def hx_redirect(request: Request, url: str) -> Response:
    if is_htmx(request):
        return Response(status_code=204, headers={"HX-Redirect": url})
    return RedirectResponse(url, status_code=303)


# ---------------------------------------------------------------- context builders


def list_ctx(session: Session, current_id: int | None = None) -> dict:
    return {
        "heroes": repo.list_heroes(session),
        "lanes_by_hero": repo.get_all_lanes(session),
        "current_id": current_id,
    }


def stats_ctx(session: Session) -> dict:
    return {"stats": repo.get_stats(session)}


def basic_ctx(session: Session, hero: Hero, message: str | None = None) -> dict:
    stats = repo.get_stats(session)
    return {
        "hero": hero,
        "group_members": stats.form_groups.get(hero.form_group, []) if hero.form_group else [],
        "message": message,
    }


def lanes_ctx(session: Session, hero: Hero) -> dict:
    return {"hero": hero, "lanes": repo.get_lanes(session, hero.id)}


def editor_ctx(session: Session, hero: Hero) -> dict:
    all_lanes = repo.get_all_lanes(session)
    return {
        **basic_ctx(session, hero),
        **lanes_ctx(session, hero),
        "others": [h for h in repo.list_heroes(session) if h.id != hero.id],
        "lanes_by_hero": all_lanes,
        "counters": repo.counters_of(session, hero.id),
        "synergies": repo.synergies_of(session, hero.id),
    }


def current_hero_id(request: Request) -> int | None:
    url = request.headers.get("HX-Current-URL", "")
    marker = "/admin/hero/"
    if marker in url:
        tail = url.split(marker, 1)[1].split("?")[0].strip("/")
        if tail.isdigit():
            return int(tail)
    return None


# ---------------------------------------------------------------- pages


@router.get("", response_class=HTMLResponse)
def index(request: Request, session: Session = SessionDep):
    return render(request, "index.html", {**list_ctx(session), **stats_ctx(session), "mode": "empty"})


@router.get("/hero/new", response_class=HTMLResponse)
def new_hero_page(request: Request, session: Session = SessionDep):
    if is_htmx(request):
        return render(request, "_editor_new.html", {})
    return render(request, "index.html", {**list_ctx(session), **stats_ctx(session), "mode": "new"})


@router.get("/hero/{hero_id}", response_class=HTMLResponse)
def hero_page(hero_id: int, request: Request, session: Session = SessionDep):
    hero = session.get(Hero, hero_id)
    if hero is None:
        return hx_redirect(request, "/admin")
    ctx = editor_ctx(session, hero)
    if is_htmx(request):
        return render(request, "_editor.html", ctx)
    return render(request, "index.html", {**list_ctx(session, hero_id), **stats_ctx(session), **ctx, "mode": "edit"})


@router.get("/heroes", response_class=HTMLResponse)
def hero_list(request: Request, session: Session = SessionDep):
    return render(request, "_hero_list.html", list_ctx(session, current_hero_id(request)))


@router.get("/stats", response_class=HTMLResponse)
def stats(request: Request, session: Session = SessionDep):
    return render(request, "_stats.html", stats_ctx(session))


# ---------------------------------------------------------------- hero CRUD


@router.post("/hero")
def create_hero(
    request: Request,
    name: str = Form(""),
    main_class: str = Form(""),
    sub_class: str = Form(""),
    session: Session = SessionDep,
):
    hero = repo.create_hero(session, name, main_class, sub_class)
    save(session)
    return hx_redirect(request, f"/admin/hero/{hero.id}")


@router.post("/hero/{hero_id}/basic", response_class=HTMLResponse)
def update_basic(
    hero_id: int,
    request: Request,
    name: str = Form(""),
    main_class: str = Form(""),
    sub_class: str = Form(""),
    session: Session = SessionDep,
):
    hero = repo.update_hero(session, hero_id, name, main_class, sub_class)
    save(session)
    return render(request, "_basic.html", basic_ctx(session, hero, "已儲存"),
                  trigger="heroesChanged, statsChanged")


@router.post("/hero/{hero_id}/review", response_class=HTMLResponse)
def review(hero_id: int, request: Request, session: Session = SessionDep):
    hero = repo.mark_reviewed(session, hero_id)
    save(session)
    return render(request, "_basic.html", basic_ctx(session, hero, "已標記為已確認"),
                  trigger="heroesChanged, statsChanged")


@router.post("/hero/{hero_id}/avatar", response_class=HTMLResponse)
def upload_avatar(
    hero_id: int,
    request: Request,
    file: UploadFile = File(...),
    session: Session = SessionDep,
):
    data = file.file.read(repo.MAX_AVATAR_BYTES + 1)
    hero = repo.save_avatar(session, hero_id, file.filename or "", data)
    save(session)
    return render(request, "_basic.html", basic_ctx(session, hero, "頭像已更新"),
                  trigger="heroesChanged")


@router.post("/hero/{hero_id}/delete")
def delete_hero(hero_id: int, request: Request, session: Session = SessionDep):
    repo.delete_hero(session, hero_id)
    save(session)
    return hx_redirect(request, "/admin")


# ---------------------------------------------------------------- lanes


@router.post("/hero/{hero_id}/lanes/{lane}", response_class=HTMLResponse)
def set_lane(
    hero_id: int,
    lane: str,
    request: Request,
    enabled: str = Form(""),
    tier: str = Form(""),
    session: Session = SessionDep,
):
    hero = repo.get_hero(session, hero_id)
    was_enabled = lane in repo.get_lanes(session, hero_id)
    on = enabled == "on"
    # A freshly checked lane always starts unrated.
    repo.set_lane(session, hero_id, lane, on, tier if (on and was_enabled) else None)
    save(session)
    return render(request, "_lanes.html", lanes_ctx(session, hero), trigger="heroesChanged, statsChanged")


# ---------------------------------------------------------------- relations


def _rel_response(request: Request, session: Session, hero_id: int, other_id: int):
    other = repo.get_hero(session, other_id)
    return render(
        request,
        "_rel_cell.html",
        {
            "hero_id": hero_id,
            "o": other,
            "c": repo.get_counter(session, hero_id, other_id),
            "s": repo.get_synergy(session, hero_id, other_id),
            "lanes_by_hero": {other_id: repo.get_lanes(session, other_id)},
        },
        trigger="statsChanged",
    )


@router.post("/hero/{hero_id}/counter/{other_id}", response_class=HTMLResponse)
def cycle_counter(hero_id: int, other_id: int, request: Request, session: Session = SessionDep):
    value = repo.next_counter_value(repo.get_counter(session, hero_id, other_id))
    repo.set_counter(session, hero_id, other_id, value)
    save(session)
    return _rel_response(request, session, hero_id, other_id)


@router.post("/hero/{hero_id}/synergy/{other_id}", response_class=HTMLResponse)
def cycle_synergy(hero_id: int, other_id: int, request: Request, session: Session = SessionDep):
    value = repo.next_synergy_value(repo.get_synergy(session, hero_id, other_id))
    repo.set_synergy(session, hero_id, other_id, value)
    save(session)
    return _rel_response(request, session, hero_id, other_id)
