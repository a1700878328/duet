import { useEffect, useMemo, useState } from "react";
import { useNavigate } from "react-router-dom";
import { api, ApiError } from "../lib/api";
import type { AgentTask } from "../lib/types";

const TUTORIALS = ["", "portrait", "full"];

function extraBodyText(task: AgentTask): string {
  return JSON.stringify(task.extra_body ?? {}, null, 2);
}

export function AgentsPage() {
  const navigate = useNavigate();
  const [agents, setAgents] = useState<AgentTask[]>([]);
  const [selected, setSelected] = useState<string>("");
  const [prompt, setPrompt] = useState("");
  const [tutorial, setTutorial] = useState("");
  const [jailbreak, setJailbreak] = useState(false);
  const [temperature, setTemperature] = useState("0.9");
  const [maxTokens, setMaxTokens] = useState("800");
  const [timeout, setTimeoutValue] = useState("120");
  const [extraBody, setExtraBody] = useState("{}");
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);

  const current = useMemo(
    () => agents.find((item) => item.name === selected) ?? null,
    [agents, selected],
  );

  useEffect(() => {
    let cancelled = false;
    async function load() {
      setLoading(true);
      try {
        const data = await api.listAgents();
        if (cancelled) return;
        setAgents(data);
        setSelected((prev) => prev || data[0]?.name || "");
        setError(null);
      } catch (err) {
        if (!cancelled) {
          setError(err instanceof ApiError ? err.message : "加载失败");
        }
      } finally {
        if (!cancelled) setLoading(false);
      }
    }
    void load();
    return () => {
      cancelled = true;
    };
  }, []);

  useEffect(() => {
    if (!current) return;
    setPrompt(current.system_prompt);
    setTutorial(current.tutorial_name);
    setJailbreak(current.jailbreak);
    setTemperature(String(current.temperature));
    setMaxTokens(String(current.max_tokens));
    setTimeoutValue(String(current.timeout));
    setExtraBody(extraBodyText(current));
    setNotice(null);
    setError(null);
  }, [current]);

  function replaceAgent(updated: AgentTask) {
    setAgents((prev) =>
      prev.map((item) => (item.name === updated.name ? updated : item)),
    );
  }

  async function save() {
    if (!current) return;
    let parsedExtra: Record<string, unknown>;
    try {
      parsedExtra = JSON.parse(extraBody || "{}") as Record<string, unknown>;
      if (!parsedExtra || Array.isArray(parsedExtra) || typeof parsedExtra !== "object") {
        throw new Error("extra_body must be object");
      }
    } catch {
      setError("extra_body 必须是 JSON object");
      return;
    }
    setSaving(true);
    setError(null);
    setNotice(null);
    try {
      const updated = await api.updateAgent(current.name, {
        system_prompt: prompt,
        tutorial_name: tutorial,
        jailbreak,
        temperature: Number(temperature),
        max_tokens: Number(maxTokens),
        timeout: Number(timeout),
        extra_body: parsedExtra,
      });
      replaceAgent(updated);
      setNotice("已保存");
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "保存失败");
    } finally {
      setSaving(false);
    }
  }

  async function reset() {
    if (!current) return;
    if (!window.confirm(`恢复 ${current.name} 的默认配置？`)) return;
    setSaving(true);
    setError(null);
    setNotice(null);
    try {
      const updated = await api.resetAgent(current.name);
      replaceAgent(updated);
      setNotice("已恢复默认");
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "恢复失败");
    } finally {
      setSaving(false);
    }
  }

  return (
    <div className="agent-admin">
      <header className="agent-admin-head">
        <div>
          <h2>Agent Prompts</h2>
          <span>{agents.length} tasks</span>
        </div>
        <div className="row">
          <button className="btn btn-ghost" onClick={() => navigate("/rooms")}>
            房间
          </button>
          <button className="btn btn-primary" disabled={!current || saving} onClick={save}>
            {saving ? "保存中" : "保存"}
          </button>
        </div>
      </header>

      {error && <div className="agent-alert agent-alert-error">{error}</div>}
      {notice && <div className="agent-alert">{notice}</div>}

      <main className="agent-admin-grid">
        <aside className="agent-list">
          {loading && <div className="muted">Loading...</div>}
          {agents.map((item) => (
            <button
              key={item.name}
              className={`agent-list-item ${item.name === selected ? "active" : ""}`}
              onClick={() => setSelected(item.name)}
            >
              <span>{item.name}</span>
              <small>{item.output_schema}</small>
              {item.overridden && <b>modified</b>}
            </button>
          ))}
        </aside>

        <section className="agent-editor">
          {current ? (
            <>
              <div className="agent-editor-top">
                <div>
                  <h3>{current.name}</h3>
                  <span>
                    {current.overridden ? `覆盖：${current.overrides.join(", ")}` : "默认配置"}
                  </span>
                </div>
                <button className="btn btn-ghost" disabled={saving} onClick={reset}>
                  恢复默认
                </button>
              </div>

              <div className="agent-controls">
                <label className="field">
                  <span>tutorial</span>
                  <select
                    className="input"
                    value={tutorial}
                    onChange={(event) => setTutorial(event.target.value)}
                  >
                    {TUTORIALS.map((item) => (
                      <option key={item || "none"} value={item}>
                        {item || "none"}
                      </option>
                    ))}
                  </select>
                </label>
                <label className="field">
                  <span>temperature</span>
                  <input
                    className="input"
                    type="number"
                    min="0"
                    max="2"
                    step="0.05"
                    value={temperature}
                    onChange={(event) => setTemperature(event.target.value)}
                  />
                </label>
                <label className="field">
                  <span>max tokens</span>
                  <input
                    className="input"
                    type="number"
                    min="1"
                    value={maxTokens}
                    onChange={(event) => setMaxTokens(event.target.value)}
                  />
                </label>
                <label className="field">
                  <span>timeout</span>
                  <input
                    className="input"
                    type="number"
                    min="1"
                    value={timeout}
                    onChange={(event) => setTimeoutValue(event.target.value)}
                  />
                </label>
                <label className="agent-toggle">
                  <input
                    type="checkbox"
                    checked={jailbreak}
                    onChange={(event) => setJailbreak(event.target.checked)}
                  />
                  <span>NSFW directive</span>
                </label>
              </div>

              <label className="field agent-prompt-field">
                <span>system prompt</span>
                <textarea
                  className="input agent-prompt"
                  value={prompt}
                  spellCheck={false}
                  onChange={(event) => setPrompt(event.target.value)}
                />
              </label>

              <label className="field">
                <span>extra_body</span>
                <textarea
                  className="input agent-extra"
                  value={extraBody}
                  spellCheck={false}
                  onChange={(event) => setExtraBody(event.target.value)}
                />
              </label>
            </>
          ) : (
            <div className="muted">No agent selected</div>
          )}
        </section>
      </main>
    </div>
  );
}
