# -*- coding: utf-8 -*-
# pylint:disable=no-name-in-module
from alias_sandbox import AliasSandbox

with AliasSandbox() as sandbox:
    print(sandbox.desktop_url)
    input("Press Enter to continue...")
    print(sandbox.sandbox_id)
    print(sandbox.run_ipython_cell("import time\ntime.sleep(1)"))
    print(
        sandbox.call_tool(
            "browser_navigate",
            arguments={"url": "https://www.google.com/"},
        ),
    )
    input("Press Enter to continue...")
