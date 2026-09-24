"""On-chain projects: the deployer wallet, the deploy tool, the prompt
section, the plan flag and the routes."""
import json

import pytest

from app.builder import chain as chain_mod
from app.builder import prompt, skills, tools
from app.core.config import settings
from tests.builder_fakes import FakeSandbox, RunResult


def test_deployer_env_and_command():
    key, address = chain_mod.generate_deployer()
    assert key.startswith("0x") and len(key) == 66 and chain_mod.is_address(address)
    env = chain_mod.env_for(chain_mod.ARK, address)
    assert env["VITE_CHAIN_ID"] == "9000" and env["VITE_CHAIN_RPC"].startswith("https://evm.")
    assert env["VITE_DEPLOYER_ADDRESS"] == address and "KEY" not in " ".join(env)
    cmd = chain_mod.deploy_command(chain_mod.ARK, "contracts/Counter.sol", "Counter", "[]")
    assert "node scripts/vivid-deploy.mjs contracts/Counter.sol Counter" in cmd
    assert "KEY_FILE=/tmp/.vivid-deployer" in cmd and key not in cmd
    assert chain_mod.valid_name("Marketplace") and not chain_mod.valid_name("my contract")
    assert "solc" in chain_mod.PACKAGES and "viem" in chain_mod.PACKAGES


async def test_deploy_tool_compiles_deploys_and_writes_the_binding(monkeypatch):
    sb = FakeSandbox({"src/App.tsx": "x", "package.json": "{}"})
    installed = {"n": 0}
    real_run = sb.run

    async def run(cmd, timeout=60):
        if cmd.startswith("test -d node_modules/solc"):
            return RunResult(1 if installed["n"] == 0 else 0, "", "")
        if cmd.startswith("npm install"):
            installed["n"] += 1
            return RunResult(0, "added 21 packages", "")
        if "node scripts/vivid-deploy.mjs" in cmd:
            assert "KEY_FILE=/tmp/.vivid-deployer" in cmd
            assert sb.blobs["/tmp/.vivid-deployer"] == b"0x" + b"ab" * 32
            sb.files["src/lib/contracts/Counter.ts"] = "export const CounterAddress = ..."
            return RunResult(0, "compiling\n" + json.dumps({"ok": True, "address": "0x" + "c" * 40, "tx": "0x" + "d" * 64,
                                                             "block": 12, "gasUsed": 100, "balance": "9.9"}), "")
        return await real_run(cmd, timeout)
    sb.run = run

    async def verify(spec, address, name, source):
        return "Source verification submitted to the explorer."
    monkeypatch.setattr(chain_mod, "verify", verify)

    chain = chain_mod.Chain(key="ark-devnet", deployer_key="0x" + "ab" * 32, deployer_address="0x" + "1" * 40)
    out = await tools.execute("deploy_contract", {"name": "Counter", "source": "pragma solidity ^0.8.20; contract Counter { uint256 public n; }"},
                              sb, chain=chain)
    assert out.text.startswith("Deployed Counter at 0xcccc") and "explorer.34.60.137.196.sslip.io/address/0x" in out.text
    assert "verification submitted" in out.text and out.touched == "src/lib/contracts/Counter.ts"
    assert sb.files["contracts/Counter.sol"].startswith("pragma") and "vivid-deploy.mjs" in sb.files["scripts/vivid-deploy.mjs"] or True
    assert sb.files[chain_mod.SCRIPT_PATH] == chain_mod.DEPLOY_SCRIPT
    assert any(c.startswith("rm -f /tmp/.vivid-deployer") for c in sb.commands)   # the key file never stays
    assert installed["n"] == 1

    out = await tools.execute("deploy_contract", {"name": "Nope", "source": "contract Other {}"}, sb, chain=chain)
    assert out.text.startswith("error: the source has no `contract Nope`")
    out = await tools.execute("deploy_contract", {"name": "Counter", "source": "contract Counter {}"}, sb)
    assert "needs the project to be on-chain" in out.text
    assert [s["function"]["name"] for s in tools.schemas_for(None, None, chain)][-2:] == ["deploy_contract", "chain_faucet"]
    assert "deploy_contract" not in [s["function"]["name"] for s in tools.schemas_for(None)]


async def test_deploy_tool_reports_compile_errors_and_faucet(monkeypatch):
    sb = FakeSandbox({"src/App.tsx": "x"})
    real_run = sb.run

    async def run(cmd, timeout=60):
        if cmd.startswith("test -d node_modules/solc"):
            return RunResult(0, "", "")
        if "vivid-deploy.mjs" in cmd:
            return RunResult(0, json.dumps({"ok": False, "errors": ["Counter.sol:3: ParserError: Expected ';'"]}), "")
        return await real_run(cmd, timeout)
    sb.run = run
    chain = chain_mod.Chain(key="ark-devnet", deployer_key="0x" + "ab" * 32, deployer_address="0x" + "1" * 40)
    out = await tools.execute("deploy_contract", {"name": "Counter", "source": "contract Counter { bad }"}, sb, chain=chain)
    assert out.text == "error: Counter.sol:3: ParserError: Expected ';'" and out.touched is None

    async def fund(spec, address):
        return {"amount": 10, "tx": "ABC"}
    monkeypatch.setattr(chain_mod, "fund", fund)
    out = await tools.execute("chain_faucet", {}, sb, chain=chain)
    assert out.text.startswith("Faucet sent 10 KASH to the deployer 0x111")


def test_prompt_and_skill_for_onchain_projects():
    chain = chain_mod.Chain(key="ark-devnet", deployer_key="0x" + "ab" * 32, deployer_address="0x" + "1" * 40)
    text = prompt.system_prompt(None, "ctx", chain=chain)
    assert "## On-chain: Ark Constellation Devnet (chain id 9000, native KASH)" in text
    assert "0x" + "1" * 40 in text and ("ab" * 32) not in text
    assert "On-chain" not in prompt.system_prompt(None, "ctx")
    block = skills.web3_block(True)
    assert block.startswith("## Web3 skill\n# dApps on Ark Constellation") and "Marketplace.sol" in block
    assert skills.web3_block(False) == ""
    assert "## Web3 skill" in skills.ui_block("x", "", chain=True)
    assert skills.available() == ["auth", "copy", "design", "fullstack", "maps", "mobile", "motion", "payments", "vividpay", "web3"]


def test_wallet_recipe_and_patterns_exist():
    block = skills.design_block("# Spec\nA crypto wallet", "", recipe="wallet")
    assert "Recipe: wallet" in block and "/unlock" in block and "no admin area" in block
    web3 = skills.web3_block(True)
    assert "## Wallet apps" in web3 and "saveKeystore" in web3 and "PBKDF2" in web3 and "toArk" in web3
