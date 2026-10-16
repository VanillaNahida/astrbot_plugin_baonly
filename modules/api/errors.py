class ApiError(Exception):
    pass


class EventNotFound(ApiError):
    def __init__(self, event_id: str):
        super().__init__("未找到该活动，可能已删除或已下架")
        self.event_id = event_id
