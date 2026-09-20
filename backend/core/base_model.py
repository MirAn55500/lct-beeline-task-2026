from sqlmodel import SQLModel

class BaseTable(SQLModel):
    """Общий класс для всех таблиц проекта - нужен для сбора метаданных SQLModel"""
    pass
