"""Use Claw-Eval's own runner, prompt composer, tools and media policy as H0."""


def run(api):
    return api.execute_upstream(api.prompt)
