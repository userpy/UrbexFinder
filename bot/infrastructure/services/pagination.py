class PaginationControl:
    def __init__(self, start_line, end_line, array):
        self.start_line = start_line
        self.end_line = end_line
        self.array_lenth = len(array)
    async def is_start(self):
        return self.start_line == 0
    async def is_end(self):
        return self.end_line >= self.array_lenth
