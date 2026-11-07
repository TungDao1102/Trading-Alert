"""The Phase 25 Demo scenario package: catalog, harness, one module per scenario (25-08).

TEST_ONLY: a scenario is one `async def run(env, recorder) -> str` shared by the CI twin (the fake
composed process, labelled SYNTHETIC) and the owner's Demo test (D-04, D-05). Nothing under `src`
imports this package.
"""
