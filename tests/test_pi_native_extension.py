"""End-to-end tests for the generated pi-native bridge extension."""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest


def test_delivery_cap_drops_followup_without_failed_session_status(
    tmp_path: Path,
) -> None:
    """The extension must not terminal-fail a session when follow-up delivery caps.

    This runs the real JavaScript extension under Node with a real inbox payload
    and mocked Pi/fetch boundaries. Five consecutive ``sendUserMessage`` throws
    should consume the inbox file and emit an informational conversation item,
    never ``external_session_status`` with ``status: "failed"``.
    """
    node = shutil.which("node")
    if node is None:
        pytest.skip("node is required for the pi-native extension e2e test")

    extension_path = (
        Path(__file__).resolve().parents[1]
        / "omnigent"
        / "resources"
        / "pi_native"
        / "omnigent_pi_native_extension.js"
    )

    script = r"""
const assert = require("assert").strict;
const fs = require("fs");
const path = require("path");

const extensionPath = process.argv[1];
const tmpDir = process.argv[2];
const inboxDir = path.join(tmpDir, "inbox");
const payloadPath = path.join(inboxDir, "000-msg.json");
const configPath = path.join(tmpDir, "config.json");

fs.mkdirSync(inboxDir, { recursive: true });
fs.writeFileSync(
  payloadPath,
  JSON.stringify({ id: "msg-1", type: "user_message", content: "follow up" }),
);
fs.writeFileSync(
  configPath,
  JSON.stringify({
    serverUrl: "http://omnigent.test",
    sessionId: "session-1",
    inboxDir,
    authHeaders: { authorization: "Bearer test" },
  }),
);

process.env.OMNIGENT_PI_NATIVE_CONFIG = configPath;

const postedEvents = [];
global.fetch = async (_url, request) => {
  postedEvents.push(JSON.parse(request.body));
  return { ok: true };
};

let pollInbox = null;
global.setInterval = (fn, _ms) => {
  pollInbox = fn;
  return { fakeInterval: true };
};

const handlers = {};
const sendAttempts = [];
const pi = {
  registerCommand() {},
  on(eventName, handler) {
    handlers[eventName] = handler;
  },
  sendUserMessage(content, options) {
    sendAttempts.push({ content, options });
    throw new Error("Pi is not ready");
  },
};

require(extensionPath)(pi);

(async () => {
  assert.equal(typeof handlers.session_start, "function");
  await handlers.session_start({}, {
    sessionManager: { getSessionId: () => "native-session-1" },
    ui: { setTitle() {}, setStatus() {}, notify() {} },
  });
  assert.equal(typeof pollInbox, "function");

  for (let attempt = 0; attempt < 5; attempt += 1) {
    pollInbox();
  }
  await new Promise((resolve) => setImmediate(resolve));

  assert.deepEqual(
    sendAttempts,
    Array.from({ length: 5 }, () => ({
      content: "follow up",
      options: { deliverAs: "followUp" },
    })),
  );
  assert.equal(fs.existsSync(payloadPath), false);
  assert.equal(
    postedEvents.some(
      (event) =>
        event.type === "external_session_status" &&
        event.data &&
        event.data.status === "failed",
    ),
    false,
    JSON.stringify(postedEvents),
  );

  const dropNote = postedEvents.find(
    (event) =>
      event.type === "external_conversation_item" &&
      event.data &&
      event.data.item_type === "error" &&
      event.data.item_data &&
      event.data.item_data.code === "pi_followup_delivery_dropped",
  );
  assert.ok(dropNote, JSON.stringify(postedEvents));
  assert.equal(dropNote.data.item_data.source, "execution");
  assert.match(dropNote.data.response_id, /^pi-deliver-dropped-/);
  // The note must be actionable: include the dropped message id and a preview
  // of its content so an operator can identify what was lost.
  assert.match(dropNote.data.item_data.message, /msg-1/);
  assert.match(dropNote.data.item_data.message, /follow up/);
})().catch((error) => {
  console.error(error && error.stack ? error.stack : error);
  process.exit(1);
});
"""

    result = subprocess.run(
        [node, "-e", script, str(extension_path), str(tmp_path)],
        capture_output=True,
        check=False,
        text=True,
        timeout=10,
    )

    assert result.returncode == 0, result.stdout + result.stderr


def _run_extension_script(node: str, extension_path: Path, script: str) -> None:
    """Run a Node test ``script`` against the real extension; fail on nonzero exit."""
    result = subprocess.run(
        [node, "-e", script, str(extension_path)],
        capture_output=True,
        check=False,
        text=True,
        timeout=10,
    )
    assert result.returncode == 0, result.stdout + result.stderr


def _usage_test_preamble() -> str:
    """Shared Node harness: load the extension with a mocked fetch + Pi.

    Exposes ``postedEvents`` (parsed request bodies), ``handlers`` (the
    registered Pi event handlers), and a ``ctx`` stub.
    """
    return r"""
const assert = require("assert").strict;
const path = require("path");

const extensionPath = process.argv[1];
const configPath = path.join(require("os").tmpdir(), `pi-usage-${process.pid}.json`);
require("fs").writeFileSync(
  configPath,
  JSON.stringify({
    serverUrl: "http://omnigent.test",
    sessionId: "session-1",
    authHeaders: { authorization: "Bearer test" },
  }),
);
process.env.OMNIGENT_PI_NATIVE_CONFIG = configPath;

const postedEvents = [];
global.fetch = async (_url, request) => {
  postedEvents.push(JSON.parse(request.body));
  return { ok: true };
};
global.setInterval = () => ({ fakeInterval: true });

const handlers = {};
const pi = {
  registerCommand() {},
  on(eventName, handler) {
    handlers[eventName] = handler;
  },
};
require(extensionPath)(pi);

const ctx = { ui: { setTitle() {}, setStatus() {}, notify() {} } };

function usageEvents() {
  return postedEvents.filter((e) => e.type === "external_session_usage");
}
"""


def test_message_end_posts_external_session_usage(tmp_path: Path) -> None:
    """A ``message_end`` with Pi usage POSTs ``external_session_usage``.

    Asserts the cumulative token fields and model match what the server prices
    (input is INCLUSIVE of cache reads; cache split sent separately).
    """
    node = shutil.which("node")
    if node is None:
        pytest.skip("node is required for the pi-native extension e2e test")
    extension_path = (
        Path(__file__).resolve().parents[1]
        / "omnigent"
        / "resources"
        / "pi_native"
        / "omnigent_pi_native_extension.js"
    )

    script = (
        _usage_test_preamble()
        + r"""
(async () => {
  assert.equal(typeof handlers.message_end, "function");
  await handlers.message_end(
    {
      message: {
        role: "assistant",
        model: "databricks-claude-sonnet-4-6",
        content: [{ type: "text", text: "hi" }],
        usage: {
          input: 100,
          output: 40,
          cacheRead: 30,
          cacheWrite: 10,
          totalTokens: 180,
        },
      },
    },
    ctx,
  );

  const usage = usageEvents();
  assert.equal(usage.length, 1, JSON.stringify(postedEvents));
  const data = usage[0].data;
  // input total is INCLUSIVE of cacheRead + cacheWrite (the server splits the
  // cache-read portion back out): 100 + 30 + 10 = 140.
  assert.equal(data.cumulative_input_tokens, 140);
  assert.equal(data.cumulative_output_tokens, 40);
  assert.equal(data.cumulative_cache_read_input_tokens, 30);
  assert.equal(data.model, "databricks-claude-sonnet-4-6");
})().catch((error) => {
  console.error(error && error.stack ? error.stack : error);
  process.exit(1);
});
"""
    )
    _run_extension_script(node, extension_path, script)


def test_usage_accumulates_and_dedupes_across_messages(tmp_path: Path) -> None:
    """Per-message usage SUMS into cumulative totals; a re-emitted message is deduped."""
    node = shutil.which("node")
    if node is None:
        pytest.skip("node is required for the pi-native extension e2e test")
    extension_path = (
        Path(__file__).resolve().parents[1]
        / "omnigent"
        / "resources"
        / "pi_native"
        / "omnigent_pi_native_extension.js"
    )

    script = (
        _usage_test_preamble()
        + r"""
(async () => {
  const msgA = {
    id: "msg-a",
    role: "assistant",
    model: "databricks-claude-sonnet-4-6",
    usage: { input: 100, output: 40, cacheRead: 0, cacheWrite: 0, totalTokens: 140 },
  };
  const msgB = {
    id: "msg-b",
    role: "assistant",
    model: "databricks-claude-sonnet-4-6",
    usage: { input: 200, output: 60, cacheRead: 50, cacheWrite: 0, totalTokens: 310 },
  };

  await handlers.message_end({ message: msgA }, ctx);
  await handlers.message_end({ message: msgB }, ctx);
  // Re-emit msgB on turn_end (same id) — must NOT double-count.
  await handlers.turn_end({ message: msgB }, ctx);

  const usage = usageEvents();
  // Two distinct flushes (after A, after B); turn_end re-emit is deduped so it
  // neither counts nor re-POSTs.
  assert.equal(usage.length, 2, JSON.stringify(postedEvents));
  const last = usage[usage.length - 1].data;
  // input: (100) + (200 + 50) = 350 ; output: 40 + 60 = 100 ; cacheRead: 50.
  assert.equal(last.cumulative_input_tokens, 350);
  assert.equal(last.cumulative_output_tokens, 100);
  assert.equal(last.cumulative_cache_read_input_tokens, 50);
})().catch((error) => {
  console.error(error && error.stack ? error.stack : error);
  process.exit(1);
});
"""
    )
    _run_extension_script(node, extension_path, script)


def test_no_usage_message_posts_nothing(tmp_path: Path) -> None:
    """A message with no usage (or empty usage / non-assistant role) POSTs no usage event."""
    node = shutil.which("node")
    if node is None:
        pytest.skip("node is required for the pi-native extension e2e test")
    extension_path = (
        Path(__file__).resolve().parents[1]
        / "omnigent"
        / "resources"
        / "pi_native"
        / "omnigent_pi_native_extension.js"
    )

    script = (
        _usage_test_preamble()
        + r"""
(async () => {
  // No usage object.
  await handlers.message_end(
    { message: { role: "assistant", content: [{ type: "text", text: "hi" }] } },
    ctx,
  );
  // Empty usage (all zeros) — treated as "no usage".
  await handlers.message_end(
    {
      message: {
        role: "assistant",
        usage: { input: 0, output: 0, cacheRead: 0, cacheWrite: 0, totalTokens: 0 },
      },
    },
    ctx,
  );
  // Non-assistant role.
  await handlers.message_end(
    { message: { role: "user", usage: { input: 5, output: 0 } } },
    ctx,
  );

  assert.equal(usageEvents().length, 0, JSON.stringify(postedEvents));
})().catch((error) => {
  console.error(error && error.stack ? error.stack : error);
  process.exit(1);
});
"""
    )
    _run_extension_script(node, extension_path, script)


def test_distinct_messages_with_identical_usage_are_not_collapsed(
    tmp_path: Path,
) -> None:
    """Two DISTINCT Pi messages with identical token counts each count once.

    Pi's ``AssistantMessage`` (``@earendil-works/pi-ai``) carries NO ``id`` —
    only an optional ``responseId`` and a required numeric ``timestamp``. Two
    genuinely distinct LLM calls can report identical ``usage`` (e.g. two
    identical short acks under prompt caching); keying dedup on the usage
    counts alone would collapse the second call and UNDERCOUNT the session.
    The dedup must key on the message identity (``timestamp`` here), so both
    calls accumulate; re-emitting the SAME message (same ``timestamp``) on
    ``turn_end`` must still dedupe.
    """
    node = shutil.which("node")
    if node is None:
        pytest.skip("node is required for the pi-native extension e2e test")
    extension_path = (
        Path(__file__).resolve().parents[1]
        / "omnigent"
        / "resources"
        / "pi_native"
        / "omnigent_pi_native_extension.js"
    )

    script = (
        _usage_test_preamble()
        + r"""
(async () => {
  // Real Pi shape: no `id`, distinct required `timestamp`, IDENTICAL usage.
  const usage = { input: 100, output: 40, cacheRead: 0, cacheWrite: 0, totalTokens: 140 };
  const msg1 = {
    role: "assistant",
    model: "databricks-claude-sonnet-4-6",
    timestamp: 1000,
    usage: { ...usage },
  };
  const msg2 = {
    role: "assistant",
    model: "databricks-claude-sonnet-4-6",
    timestamp: 2000,
    usage: { ...usage },
  };

  await handlers.message_end({ message: msg1 }, ctx);
  await handlers.message_end({ message: msg2 }, ctx);
  // Re-emit msg2 (same timestamp) on turn_end — must NOT double-count.
  await handlers.turn_end({ message: msg2 }, ctx);

  const events = usageEvents();
  // Two distinct flushes (after msg1, after msg2); the re-emit is deduped.
  assert.equal(events.length, 2, JSON.stringify(postedEvents));
  const last = events[events.length - 1].data;
  // BOTH distinct calls counted despite identical usage: input 100+100=200,
  // output 40+40=80. (A counts-only fingerprint would wrongly stay at 100/40.)
  assert.equal(last.cumulative_input_tokens, 200);
  assert.equal(last.cumulative_output_tokens, 80);
})().catch((error) => {
  console.error(error && error.stack ? error.stack : error);
  process.exit(1);
});
"""
    )
    _run_extension_script(node, extension_path, script)


def test_agent_end_dedupes_real_shaped_messages_by_timestamp(
    tmp_path: Path,
) -> None:
    """The ``agent_end`` whole-conversation re-scan dedupes real Pi messages.

    ``agent_end`` carries the full ``messages`` array and re-scans it as a
    last-chance capture. Real Pi messages have no ``id``, so the dedup keys on
    ``timestamp``; a message already counted on ``message_end`` must be a no-op
    when it reappears in the ``agent_end`` array (no overcount).
    """
    node = shutil.which("node")
    if node is None:
        pytest.skip("node is required for the pi-native extension e2e test")
    extension_path = (
        Path(__file__).resolve().parents[1]
        / "omnigent"
        / "resources"
        / "pi_native"
        / "omnigent_pi_native_extension.js"
    )

    script = (
        _usage_test_preamble()
        + r"""
(async () => {
  const msg = {
    role: "assistant",
    model: "databricks-claude-sonnet-4-6",
    timestamp: 4242,
    usage: { input: 300, output: 50, cacheRead: 20, cacheWrite: 10, totalTokens: 380 },
  };

  // Counted on message_end.
  await handlers.message_end({ message: msg }, ctx);
  // agent_end re-scans the whole conversation including the same message —
  // must NOT re-count it (same timestamp).
  await handlers.agent_end({ messages: [msg] }, ctx);

  const events = usageEvents();
  assert.equal(events.length, 1, JSON.stringify(postedEvents));
  const last = events[events.length - 1].data;
  // input INCLUSIVE of cacheRead + cacheWrite: 300 + 20 + 10 = 330, counted once.
  assert.equal(last.cumulative_input_tokens, 330);
  assert.equal(last.cumulative_output_tokens, 50);
  assert.equal(last.cumulative_cache_read_input_tokens, 20);
})().catch((error) => {
  console.error(error && error.stack ? error.stack : error);
  process.exit(1);
});
"""
    )
    _run_extension_script(node, extension_path, script)
