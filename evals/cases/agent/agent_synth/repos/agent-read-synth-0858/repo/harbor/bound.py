from harbor import config


def capacity(limit=config.LIMIT):
    return limit * 4
