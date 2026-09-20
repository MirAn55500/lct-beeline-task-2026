from enum import StrEnum


class DictGroup(StrEnum):
    """Сервисные имена групп словаря (`dicts.group`)."""

    PRIORITY = "priority"
    TRANSPORT = "transport"
    STATUS = "status"
    SKILL = "skill"
    REQUEST_TYPE_VK = "request_type_vk"
    REQUEST_TYPE_HD = "request_type_hd"
    EQUIPMENT_ITEM = "equipment_item"
    UPLOAD_TYPE = "upload_type"
    FILE_TYPE = "file_type"
    SNAPSHOT_ACTION = "snapshot_action"
