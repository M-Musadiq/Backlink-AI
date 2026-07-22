from typing import TypeVar, Generic, Type, Optional, List
from sqlalchemy.orm import Session
from src.infrastructure.database import Base

T = TypeVar("T", bound=Base)


class BaseRepository(Generic[T]):
    def __init__(self, session: Session, model: Type[T]):
        self._session = session
        self._model = model

    def add(self, entity: T) -> T:
        self._session.add(entity)
        self._session.commit()
        self._session.refresh(entity)
        return entity

    def get_by_id(self, entity_id: int) -> Optional[T]:
        return self._session.query(self._model).filter(self._model.id == entity_id).first()

    def get_all(self) -> List[T]:
        return self._session.query(self._model).order_by(self._model.id.asc()).all()

    def delete(self, entity: T) -> None:
        self._session.delete(entity)
        self._session.commit()

    def count(self) -> int:
        return self._session.query(self._model).count()
