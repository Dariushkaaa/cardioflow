import uuid

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.security import ensure_patient_access, get_current_patient_id
from app.core.timeutils import utcnow
from app.models.slot import AppointmentSlot
from app.schemas.slot import BookRequest, BookResponse, SlotOut, SlotsResponse

slots_router = APIRouter()
appointments_router = APIRouter()


@slots_router.get("/available", response_model=SlotsResponse)
async def get_available_slots(
    doctor_type: str = Query(default="therapist"),
    limit: int = Query(default=3, ge=1, le=50),
    db: AsyncSession = Depends(get_db),
    _patient_id: uuid.UUID = Depends(get_current_patient_id),
) -> SlotsResponse:
    """Ближайшие свободные окна записи к врачу.

    Параметр doctor_type принимается для совместимости с контрактом; в схеме БД
    (appointment_slots) нет поля типа врача, поэтому фильтрация по нему не выполняется.
    """
    result = await db.execute(
        select(AppointmentSlot)
        .where(AppointmentSlot.is_booked.is_(False), AppointmentSlot.datetime > utcnow())
        .order_by(AppointmentSlot.datetime)
        .limit(limit)
    )
    slots = [SlotOut.model_validate(slot) for slot in result.scalars().all()]
    return SlotsResponse(slots=slots)


@appointments_router.post("/book", response_model=BookResponse)
async def book_slot(
    payload: BookRequest,
    db: AsyncSession = Depends(get_db),
    token_patient_id: uuid.UUID = Depends(get_current_patient_id),
) -> BookResponse:
    """Бронирование выбранного слота (атомарно, без двойного бронирования)."""
    ensure_patient_access(token_patient_id, payload.patient_id)

    slot = await db.get(AppointmentSlot, payload.slot_id)
    if slot is None:
        raise HTTPException(status_code=404, detail="Слот не найден")
    if slot.datetime <= utcnow():
        raise HTTPException(status_code=400, detail="Слот уже в прошлом")

    result = await db.execute(
        update(AppointmentSlot)
        .where(AppointmentSlot.id == payload.slot_id, AppointmentSlot.is_booked.is_(False))
        .values(is_booked=True, patient_id=payload.patient_id)
    )
    if result.rowcount == 0:
        await db.rollback()
        raise HTTPException(status_code=409, detail="Слот уже занят")
    await db.commit()

    return BookResponse(status="booked", slot_id=slot.id, datetime=slot.datetime)
