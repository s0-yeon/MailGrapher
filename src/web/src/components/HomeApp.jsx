import { createRoot } from 'react-dom/client';
import Header from './Header.jsx';
import Footer from './Footer.jsx';
import HeroContent from './HeroOrbit.jsx';

/**
 * 홈 화면(index.html) 전체를 감싸는 최상위 컴포넌트.
 * 예전엔 #app-header / <main> / #app-footer 세 곳에 각각 다른 방식(innerHTML)으로
 * 내용을 채워 넣었는데, 지금은 이 컴포넌트 하나가 셋을 전부 그려냄.
 */
function HomeApp() {
  return (
    <>
      <Header activePage="home" />
      <main className="right_col" role="main" aria-label="Main content">
        <HeroContent />
      </main>
      <Footer />
    </>
  );
}

export function mountHomeApp(containerId) {
  const el = document.getElementById(containerId);
  if (!el) return;
  createRoot(el).render(<HomeApp />);
}
