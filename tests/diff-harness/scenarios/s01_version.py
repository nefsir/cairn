NAME = "version-help-banner"
def run(ctx):
    ctx.run("--version")
    ctx.run("-V")
    ctx.run("version")
    ctx.run("--help")
    ctx.run("-h")
    ctx.run("help")
    ctx.run()          # no-arg banner
    ctx.run("banner")  # explicit banner
    ctx.run("bogus")   # unknown command -> die (stderr + exit 1)
