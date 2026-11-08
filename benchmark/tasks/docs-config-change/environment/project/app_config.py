import os

def payment_settings():
    return {
        "retry_limit": int(os.getenv("PAYMENT_RETRY_LIMIT", "5")),
        "retry_delay_seconds": int(os.getenv("PAYMENT_RETRY_DELAY_SECONDS", "2")),
    }
