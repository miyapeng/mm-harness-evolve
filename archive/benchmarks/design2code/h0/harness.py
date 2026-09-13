"""Official direct-prompting starting point. Context logic is the mutation surface."""


def run(api):
    html = api.generate(api.prompt, [api.reference_image])
    api.render(html)
    return html
