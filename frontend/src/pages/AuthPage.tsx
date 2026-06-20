import { useState, type FormEvent } from "react";
import { useNavigate } from "react-router-dom";
import { api, ApiError } from "../lib/api";
import { useAuth } from "../lib/auth";
import { LanguageSelect, useI18n } from "../lib/i18n";

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
  const { t } = useI18n();
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
        err instanceof ApiError ? err.message : t("networkError"),
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
        err instanceof ApiError ? err.message : t("networkError"),
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
        <div className="auth-tools">
          <LanguageSelect compact />
        </div>
        <div className="brand">
          <h1>duet</h1>
          <p>{t("duetTagline")}</p>
        </div>

        {savedAccounts.length > 0 && (
          <div className="saved-accounts">
            <div className="saved-accounts-title">{t("savedAccounts")}</div>
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
                    aria-label={t("removeAccountLabel", { username: account.username })}
                  >
                    {t("remove")}
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
            {t("login")}
          </button>
          <button
            className={`tab ${mode === "register" ? "active" : ""}`}
            onClick={() => setMode("register")}
            type="button"
            disabled={busy !== null}
          >
            {t("register")}
          </button>
        </div>

        <form className="form" onSubmit={submit}>
          <div className="field">
            <label htmlFor="username">{t("username")}</label>
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
              <label htmlFor="display_name">{t("displayName")}</label>
              <input
                id="display_name"
                className="input"
                value={displayName}
                onChange={(e) => setDisplayName(e.target.value)}
                placeholder={t("displayNamePlaceholder")}
                disabled={busy !== null}
              />
            </div>
          )}

          <div className="field">
            <label htmlFor="password">{t("password")}</label>
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
            {busy === "form"
              ? t("pleaseWait")
              : mode === "login"
                ? t("login")
                : t("registerAndEnter")}
          </button>
        </form>
      </div>
    </div>
  );
}
