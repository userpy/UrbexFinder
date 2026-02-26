class PaginationControl:
    def __init__(self, offset, line_count , resource_count):
        self.offset = offset
        self.resource_count = resource_count
        self.line_count = line_count

    async def is_start(self):
        return self.offset == 0

    async def is_end(self):
        return (self.offset + self.line_count)  >= self.resource_count
