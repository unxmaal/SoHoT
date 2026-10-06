ROUTES = []


def route(path, methods=("GET",)):
    def wrap(fn):
        ROUTES.append((path, tuple(methods), fn.__name__))
        return fn
    return wrap
