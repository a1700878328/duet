import { useState, type FormEvent } from "react";
import { useNavigate } from "react-router-dom";
import { api, ApiError } from "../lib/api";
import { useAuth } from "../lib/auth";

type Mode = "login" | "register";
type BusyAction = "form" | `saved:${string}` | null;

interface SavedAccount {
  username: string;
  displayName: string;
  password: string;
  updatedAt: number;
}

const SAVED_ACCOUNTS_KEY = "duet.saved_accounts";

function loadSavedAccounts(): SavedAccount[] {
  const raw = localStorage.getItem(SAVED_ACCOUNTS_KEY);
  if (!raw) return [];
  try {
    const parsed = JSON.parse(raw) as SavedAccount[];
    if (!Array.isArray(parsed)) return [];
    return parsed
      .filter(
        (account) =>
          typeof account.username === "string" &&
          typeof account.password === "string" &&
          typeof account.displayName === "string",
      )
      .sort((a, b) => b.updatedAt - a.updatedAt);
  } catch {
    return [];
  }
}

function storeSavedAccounts(accounts: SavedAccount[]): void {
  localStorage.setItem(
    SAVED_ACCOUNTS_KEY,
    JSON.stringify(accounts.slice(0, 8)),
  );
}

function upsertSavedAccount(account: Omit<SavedAccount, "updatedAt">) {
  const next = [
    { ...account, updatedAt: Date.now() },
    ...loadSavedAccounts().filter((item) => item.username !== account.username),
  ];
  storeSavedAccounts(next);
  return next;
}

export function AuthPage() {
  const { setAuth } = useAuth();
  const navigate = useNavigate();
  const [mode, setMode] = useState<Mode>("login");
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [displayName, setDisplayName] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState<BusyAction>(null);
  const [savedAccounts, setSavedAccounts] = useState<SavedAccount[]>(() =>
    loadSavedAccounts(),
  );

  function rememberAccount(account: Omit<SavedAccount, "updatedAt">) {
    setSavedAccounts(upsertSavedAccount(account));
  }

  async function submit(e: FormEvent) {
    e.preventDefault();
    setError(null);
    setBusy("form");
    const enteredUsername = username.trim();
    const enteredDisplayName = displayName.trim();
    try {
      const auth =
        mode === "login"
          ? await api.login({ username: enteredUsername, password })
          : await api.register({
              username: enteredUsername,
              password,
              display_name: enteredDisplayName || enteredUsername,
            });
      rememberAccount({
        username: auth.user.username,
        displayName: auth.user.display_name,
        password,
      });
      setAuth(auth);
      navigate("/rooms", { replace: true });
    } catch (err) {
      setError(
        err instanceof ApiError ? err.message : "网络错误，请稍后再试",
      );
    } finally {
      setBusy(null);
    }
  }

  async function loginSaved(account: SavedAccount) {
    setError(null);
    setBusy(`saved:${account.username}`);
    setUsername(account.username);
    setPassword(account.password);
    try {
      const auth = await api.login({
        username: account.username,
        password: account.password,
      });
      rememberAccount({
        username: auth.user.username,
        displayName: auth.user.display_name,
        password: account.password,
      });
      setAuth(auth);
      navigate("/rooms", { replace: true });
    } catch (err) {
      setError(
        err instanceof ApiError ? err.message : "网络错误，请稍后再试",
      );
    } finally {
      setBusy(null);
    }
  }

  function forgetSavedAccount(usernameToRemove: string) {
    const next = savedAccounts.filter(
      (account) => account.username !== usernameToRemove,
    );
    storeSavedAccounts(next);
    setSavedAccounts(next);
  }

  return (
    <div className="auth-wrap">
      <div className="auth-card">
        <div className="brand">
          <h1>duet</h1>
          <p>双人协作 · AI 角色扮演</p>
        </div>

        {savedAccounts.length > 0 && (
          <div className="saved-accounts">
            <div className="saved-accounts-title">此设备账号</div>
            <div className="saved-account-list">
              {savedAccounts.map((account) => (
                <div className="saved-account-row" key={account.username}>
                  <button
                    className="saved-account-main"
                    type="button"
                    onClick={() => loginSaved(account)}
                    disabled={busy !== null}
                  >
                    <span>{account.displayName || account.username}</span>
                    <small>@{account.username}</small>
                  </button>
                  <button
                    className="saved-account-remove"
                    type="button"
                    onClick={() => forgetSavedAccount(account.username)}
                    disabled={busy !== null}
                    aria-label={`移除 ${account.username}`}
                  >
                    移除
                  </button>
                </div>
              ))}
            </div>
          </div>
        )}

        <div className="tabs">
          <button
            className={`tab ${mode === "login" ? "active" : ""}`}
            onClick={() => setMode("login")}
            type="button"
            disabled={busy !== null}
          >
            登录
          </button>
          <button
            className={`tab ${mode === "register" ? "active" : ""}`}
            onClick={() => setMode("register")}
            type="button"
            disabled={busy !== null}
          >
            注册
          </button>
        </div>

        <form className="form" onSubmit={submit}>
          <div className="field">
            <label htmlFor="username">用户名</label>
            <input
              id="username"
              className="input"
              value={username}
              autoComplete="username"
              onChange={(e) => setUsername(e.target.value)}
              disabled={busy !== null}
              required
            />
          </div>

          {mode === "register" && (
            <div className="field">
              <label htmlFor="display_name">显示名 / 角色昵称</label>
              <input
                id="display_name"
                className="input"
                value={displayName}
                onChange={(e) => setDisplayName(e.target.value)}
                placeholder="他人看到的名字"
                disabled={busy !== null}
              />
            </div>
          )}

          <div className="field">
            <label htmlFor="password">密码</label>
            <input
              id="password"
              className="input"
              type="password"
              value={password}
              autoComplete={
                mode === "login" ? "current-password" : "new-password"
              }
              onChange={(e) => setPassword(e.target.value)}
              disabled={busy !== null}
              required
            />
          </div>

          {error && <div className="error-text">{error}</div>}

          <button
            className="btn btn-primary btn-block"
            type="submit"
            disabled={busy !== null}
          >
            {busy === "form" ? "请稍候…" : mode === "login" ? "登录" : "注册并进入"}
          </button>
        </form>
      </div>
    </div>
  );
}
