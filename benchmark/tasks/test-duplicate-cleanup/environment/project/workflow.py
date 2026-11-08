class Order:
    def __init__(self):
        self.state = "draft"

    def approve(self):
        if self.state != "draft":
            raise ValueError("only drafts may be approved")
        self.state = "approved"
        return self.state

    def ship(self):
        if self.state != "approved":
            raise ValueError("only approved orders may ship")
        self.state = "shipped"
        return self.state

    def cancel(self):
        if self.state == "shipped":
            raise ValueError("shipped orders cannot be cancelled")
        self.state = "cancelled"
        return self.state
