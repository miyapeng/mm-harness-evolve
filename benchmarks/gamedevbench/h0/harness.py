"""Upstream recipe H0. Freeze the imported upstream prompt/config before baseline use."""


def run(api):
    return api.execute_upstream(api.prompt)
