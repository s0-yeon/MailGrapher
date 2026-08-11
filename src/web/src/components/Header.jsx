import { useState } from "react";
import * as DropdownMenu from "@radix-ui/react-dropdown-menu";
import { changeLanguage } from "../utils/i18n.js";

/**
 * 예전 appHeader.js의 NAV_ITEMS와 동일한 데이터. 이 배열만 고치면
 * 메뉴 항목이 늘거나 줄어도 화면이 자동으로 갱신됩니다.
 */
const NAV_ITEMS = [
  { page: "home", href: "index.html", label: "홈" },
  { page: "search", href: "search.html", label: "검색" },
  { page: "imap-collect", href: "imap-collect.html", label: "메일 수집" },
  {
    page: "mylife",
    href: "mylife.html",
    label: "My Life",
    children: [
      { page: "mypeople", href: "mypeople.html", label: "My People" },
      { page: "mytime", href: "mytime.html", label: "My Time" },
      { page: "recap", href: "recap.html", label: "Recap" },
    ],
  },
  { page: "graph-viz", href: "graph-viz.html", label: "지식 그래프" },
];

/** 언어 드롭다운 데이터 — 옵션을 추가/삭제하려면 이 배열만 고치면 됨 */
const LANG_OPTIONS = [
  { code: "ko", label: "🇰🇷 한국어", short: "KO" },
  { code: "en", label: "🇺🇸 English", short: "EN" },
  { code: "ja", label: "🇯🇵 日本語", short: "JA" },
];

function NavItem({ item, activePage }) {
  if (item.children) {
    const groupActive =
      item.page === activePage ||
      item.children.some((c) => c.page === activePage);
    return (
      <div className="gw-tl-dropdown">
        <a
          href={item.href}
          className={`gw-tl gw-tl-dd-btn${groupActive ? " active" : ""}`}
        >
          {item.label}{" "}
          <i
            className="bi bi-chevron-down"
            style={{ fontSize: ".65rem", marginLeft: "2px" }}
          ></i>
        </a>
        <div className="gw-tl-dd-menu">
          {item.children.map((c) => (
            <a
              key={c.page}
              href={c.href}
              className={c.page === activePage ? "active" : ""}
            >
              {c.label}
            </a>
          ))}
        </div>
      </div>
    );
  }
  return (
    <a
      href={item.href}
      className={`gw-tl${item.page === activePage ? " active" : ""}`}
    >
      {item.label}
    </a>
  );
}

export default function Header({ activePage }) {
  // 현재 언어 — 이 state가 바뀌면 아래 <span id="current-lang">가 자동으로 갱신됨
  const [lang, setLang] = useState("ko");

  function handleSelectLang(code) {
    setLang(code); // React가 화면(KO→EN 표시)을 즉시 갱신
    changeLanguage(code); // i18next가 실제 번역 텍스트를 페이지 전체에 적용
  }

  return (
    <div className="top_nav">
      <div className="nav_menu d-flex align-items-center justify-content-between">
        <div className="d-flex align-items-center">
          <a href="index.html" className="gw-brand-logo">
            <img
              src="/images/hero/sphere.png"
              className="gw-brand-logo-icon"
              alt=""
            />
            <span className="gw-brand-logo-text">Social Visualizer</span>
          </a>
          <nav className="gw-top-links">
            {NAV_ITEMS.map((item) => (
              <NavItem key={item.page} item={item} activePage={activePage} />
            ))}
          </nav>
        </div>
        <nav className="nav navbar-nav ms-auto">
          <ul className="navbar-right d-flex align-items-center gap-3 pe-3">
            <li className="nav-item">
              <button type="button" className="gw-login-btn">
                로그인
              </button>
            </li>
            <li className="nav-item dropdown">
              {/* Bootstrap의 data-bs-toggle 방식 대신 Radix UI 프리미티브 사용:
                  열림/닫힘, 키보드 방향키 탐색, 바깥 클릭 감지, 포커스 관리를
                  전부 라이브러리가 알아서 처리해줌 (직접 구현 X) */}
              <DropdownMenu.Root>
                <DropdownMenu.Trigger asChild>
                  <a
                    href="#"
                    role="button"
                    className="gw-lang-trigger"
                    style={{
                      textDecoration: "none",
                      cursor: "pointer",
                    }}
                  >
                    <i
                      className="bi bi-translate"
                      style={{ fontSize: "1.2rem", verticalAlign: "middle" }}
                    ></i>
                    <span
                      id="current-lang"
                      style={{ marginLeft: "4px", fontSize: ".9rem" }}
                    >
                      {LANG_OPTIONS.find((o) => o.code === lang)?.short}
                    </span>
                  </a>
                </DropdownMenu.Trigger>
                <DropdownMenu.Portal>
                  <DropdownMenu.Content
                    className="dropdown-menu show"
                    align="end"
                    sideOffset={6}
                  >
                    {LANG_OPTIONS.map((opt) => (
                      <DropdownMenu.Item
                        key={opt.code}
                        className="dropdown-item"
                        style={{ cursor: "pointer" }}
                        onSelect={() => handleSelectLang(opt.code)}
                      >
                        {opt.label}
                      </DropdownMenu.Item>
                    ))}
                  </DropdownMenu.Content>
                </DropdownMenu.Portal>
              </DropdownMenu.Root>
            </li>
          </ul>
        </nav>
      </div>
    </div>
  );
}
