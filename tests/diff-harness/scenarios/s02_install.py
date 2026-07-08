NAME = "install-then-status"
def run(ctx):
    ctx.run("install")
    ctx.run("status")
