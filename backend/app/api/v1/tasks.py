from fastapi import APIRouter, HTTPException, status, Depends
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import or_, select
from ...core.deps import get_db, require_permission, get_user_permissions
from ...core.store_scope import allowed_store_ids, store_filter
from ...models.models import Task, Store, User
from ...schemas import TaskCreate, TaskUpdate, TaskResponse

router = APIRouter(prefix="/tasks", tags=["tasks"])


@router.get("/", response_model=list[TaskResponse])
async def list_tasks(
    store_id: int = None, assigned_to: int = None, task_status: str = None,
    priority: str = None,
    db: AsyncSession = Depends(get_db),
    user: User = require_permission("tasks", "view"),
):
    query = select(Task)
    # their stores' tasks, plus anything handed to them directly
    query = query.where(or_(store_filter(Task.store_id, await allowed_store_ids(user, db)), Task.assigned_to == user.id))
    if store_id:
        query = query.where(Task.store_id == store_id)
    if assigned_to:
        query = query.where(Task.assigned_to == assigned_to)
    if task_status:
        query = query.where(Task.status == task_status)
    if priority:
        query = query.where(Task.priority == priority)
    query = query.order_by(Task.due_at.asc())
    result = await db.execute(query)
    tasks = result.scalars().all()
    store_cache = {}
    user_cache = {}
    out = []
    for t in tasks:
        if t.store_id and t.store_id not in store_cache:
            r = await db.execute(select(Store).where(Store.id == t.store_id))
            store_cache[t.store_id] = r.scalar_one_or_none()
        if t.assigned_to and t.assigned_to not in user_cache:
            r = await db.execute(select(User).where(User.id == t.assigned_to))
            user_cache[t.assigned_to] = r.scalar_one_or_none()
        st = store_cache.get(t.store_id)
        asg = user_cache.get(t.assigned_to)
        out.append(TaskResponse(
            id=t.id, title=t.title, description=t.description or "",
            type=t.type, assigned_to=t.assigned_to,
            assignee_name=asg.name if asg else "",
            store_id=t.store_id, store_name=st.name if st else "",
            due_at=t.due_at, status=t.status, priority=t.priority,
            created_at=t.created_at,
        ))
    return out


@router.post("/", response_model=TaskResponse, status_code=status.HTTP_201_CREATED)
async def create_task(
    body: TaskCreate,
    db: AsyncSession = Depends(get_db),
    user: User = require_permission("tasks", "create"),
):
    t = Task(
        title=body.title, description=body.description, type=body.type,
        assigned_to=body.assigned_to, store_id=body.store_id,
        due_at=body.due_at, status=body.status, priority=body.priority,
    )
    db.add(t)
    await db.commit()
    await db.refresh(t)
    return TaskResponse(
        id=t.id, title=t.title, description=t.description or "",
        type=t.type, assigned_to=t.assigned_to, assignee_name="",
        store_id=t.store_id, store_name="", due_at=t.due_at,
        status=t.status, priority=t.priority, created_at=t.created_at,
    )


@router.get("/{task_id}", response_model=TaskResponse)
async def get_task(
    task_id: int,
    db: AsyncSession = Depends(get_db),
    _user: User = require_permission("tasks", "view"),
):
    result = await db.execute(select(Task).where(Task.id == task_id))
    t = result.scalar_one_or_none()
    if not t:
        raise HTTPException(status_code=404, detail="Task not found")
    return TaskResponse(
        id=t.id, title=t.title, description=t.description or "",
        type=t.type, assigned_to=t.assigned_to, assignee_name="",
        store_id=t.store_id, store_name="", due_at=t.due_at,
        status=t.status, priority=t.priority, created_at=t.created_at,
    )


@router.put("/{task_id}", response_model=TaskResponse)
async def update_task(
    task_id: int, body: TaskUpdate,
    db: AsyncSession = Depends(get_db),
    _user: User = require_permission("tasks", "edit"),
):
    result = await db.execute(select(Task).where(Task.id == task_id))
    t = result.scalar_one_or_none()
    if not t:
        raise HTTPException(status_code=404, detail="Task not found")
    for field, value in body.model_dump(exclude_unset=True).items():
        setattr(t, field, value)
    await db.commit()
    await db.refresh(t)
    return TaskResponse(
        id=t.id, title=t.title, description=t.description or "",
        type=t.type, assigned_to=t.assigned_to, assignee_name="",
        store_id=t.store_id, store_name="", due_at=t.due_at,
        status=t.status, priority=t.priority, created_at=t.created_at,
    )


@router.delete("/{task_id}")
async def delete_task(
    task_id: int,
    db: AsyncSession = Depends(get_db),
    _user: User = require_permission("tasks", "delete"),
):
    result = await db.execute(select(Task).where(Task.id == task_id))
    t = result.scalar_one_or_none()
    if not t:
        raise HTTPException(status_code=404, detail="Task not found")
    await db.delete(t)
    await db.commit()
    return {"message": "Task deleted"}
