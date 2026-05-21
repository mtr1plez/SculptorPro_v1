import { useState, useEffect } from 'react';
import { Film, LayoutTemplate, Music, Scissors, Lightbulb, TrendingUp } from 'lucide-react';
import { Library } from './components/Library';
import { Projects } from './components/Projects';
import { SegmentedProjectDetail } from './components/SegmentedProjectDetail';
import { SourceDetail } from './components/SourceDetail';
import { SplashScreen } from './components/SplashScreen';
import { AudioStudio } from './components/AudioStudio';
import { ShortsGenerator } from './components/ShortsGenerator';
import { BrainstormTab } from './components/BrainstormTab';
import { TrendsTab } from './components/TrendsTab';

function App() {
  const [activeTab, setActiveTab] = useState('projects');
  const [selectedProject, setSelectedProject] = useState(null);
  const [selectedSource, setSelectedSource] = useState(null);
  const [appState, setAppState] = useState('init'); // 'init' | 'offline' | 'ready'

  // Global build progress tracking
  const [activeBuilds, setActiveBuilds] = useState({});
  // { projectName: { percent, status, step, current_track, total_tracks, track_name } }

  const checkConnectivity = () => {
    if (!navigator.onLine) {
      setAppState('offline');
      return;
    }

    const timer = setTimeout(() => {
      if (navigator.onLine) {
        setAppState('ready');
      } else {
        setAppState('offline');
      }
    }, 5000);

    return () => clearTimeout(timer);
  };

  const handleRetry = () => {
    setAppState('init');
    checkConnectivity();
  };

  useEffect(() => {
    const cleanup = checkConnectivity();
    return cleanup;
  }, []);

  // === GLOBAL WEBSOCKET FOR BUILD PROGRESS ===
  useEffect(() => {
    if (appState !== 'ready') return;

    let ws = null;
    let reconnectTimeout = null;

    const connectWebSocket = () => {
      ws = new WebSocket('ws://localhost:8000/ws/logs');

      ws.onmessage = (event) => {
        try {
          const data = JSON.parse(event.data);
          if (data.type === 'progress' && data.alias) {
            setActiveBuilds(prev => {
              // If build is complete or error, remove after delay
              if (data.percent >= 100 || (data.percent === 0 && data.status && data.status.startsWith('Error'))) {
                setTimeout(() => {
                  setActiveBuilds(p => {
                    const next = { ...p };
                    delete next[data.alias];
                    return next;
                  });
                }, 5000);
              }

              return {
                ...prev,
                [data.alias]: {
                  percent: data.percent,
                  status: data.status || '',
                  step: data.step,
                  current_track: data.current_track,
                  total_tracks: data.total_tracks,
                  track_name: data.track_name
                }
              };
            });
          }
        } catch (e) {
          // Ignore parse errors
        }
      };

      ws.onerror = () => {
        // Just let it close, the onclose handler will trigger reconnect
      };

      ws.onclose = () => {
        // Auto-reconnect after 2 seconds
        reconnectTimeout = setTimeout(connectWebSocket, 2000);
      };
    };

    connectWebSocket();

    return () => {
      clearTimeout(reconnectTimeout);
      if (ws) {
        // Remove onclose handler so we don't reconnect after component unmount
        ws.onclose = null;
        if (ws.readyState === WebSocket.OPEN) {
          ws.close();
        }
      }
    };
  }, [appState]);

  if (appState !== 'ready') {
    return (
      <SplashScreen
        status={appState === 'offline' ? 'offline' : 'loading'}
        onRetry={handleRetry}
      />
    );
  }

  const renderContent = () => {
    // 1. Source Detail (Highest priority if selected)
    if (selectedSource) {
      return (
        <SourceDetail
          source={selectedSource}
          onBack={() => setSelectedSource(null)}
        />
      );
    }

    // 2. Project Detail
    if (selectedProject) {
      return (
        <SegmentedProjectDetail
          project={selectedProject}
          onBack={() => setSelectedProject(null)}
          buildProgress={activeBuilds[selectedProject.name]}
        />
      );
    }

    // 3. Persistent Tabs (All mounted, just toggled display)
    return (
      <>
        <div style={{ display: activeTab === 'library' ? 'block' : 'none', height: '100%' }}>
          <Library onOpenSource={(source) => setSelectedSource(source)} />
        </div>
        <div style={{ display: activeTab === 'projects' ? 'block' : 'none', height: '100%' }}>
          <Projects
            onOpenProject={(proj) => setSelectedProject(proj)}
            activeBuilds={activeBuilds}
          />
        </div>
        <div style={{ display: activeTab === 'audio' ? 'block' : 'none', height: '100%' }}>
          <AudioStudio
            onProjectCreated={(proj) => {
              setActiveTab('projects');
              setSelectedProject(proj);
            }}
          />
        </div>
        <div style={{ display: activeTab === 'shorts' ? 'block' : 'none', height: '100%' }}>
          <ShortsGenerator />
        </div>
        <div style={{ display: activeTab === 'trends' ? 'block' : 'none', height: '100%' }}>
          <TrendsTab />
        </div>
        <div style={{ display: activeTab === 'brainstorm' ? 'block' : 'none', height: '100%' }}>
          <BrainstormTab />
        </div>
      </>
    );
  };

  const getNavClass = (tabName) => {
    const base = "flex items-center gap-3 w-full px-4 py-3 rounded-lg text-sm font-medium transition-all duration-200 ";
    if (activeTab === tabName) {
      return base + "bg-accent/10 text-accent shadow-[0_0_15px_rgba(59,130,246,0.1)] border border-accent/20";
    }
    return base + "text-muted hover:bg-white/5 hover:text-gray-200";
  };

  return (
    // ROOT CONTAINER:
    // flex = выстраиваем детей (Sidebar + Main) в ряд
    // h-screen = высота ровно в экран
    // w-screen = ширина ровно в экран
    // overflow-hidden = никаких скроллов на уровне окна
    <div className="flex h-screen w-screen bg-background text-primary overflow-hidden">

      {/* SIDEBAR (Скрываем, если открыт проект) */}
      {!selectedProject && (
        // w-64 = фиксированная ширина
        // flex-shrink-0 = запрещаем сжиматься, если места мало
        <aside className="w-64 flex-shrink-0 bg-surface border-r border-border flex flex-col z-10 shadow-xl">
          <div className="p-6">
            <h1 className="text-xl font-bold tracking-tight text-white flex items-center gap-2">
              <span className="text-accent">◆</span> SCULPTOR PRO
            </h1>
          </div>

          <nav className="flex-1 px-4 space-y-2">
            <button onClick={() => setActiveTab('library')} className={getNavClass('library')}>
              <Film size={18} /> Library
            </button>
            <button onClick={() => setActiveTab('projects')} className={getNavClass('projects')}>
              <LayoutTemplate size={18} /> Projects
            </button>
            <button onClick={() => setActiveTab('audio')} className={getNavClass('audio')}>
              <Music size={18} /> Studio
            </button>
            <button onClick={() => setActiveTab('shorts')} className={getNavClass('shorts')}>
              <Scissors size={18} /> Shorts
            </button>
            <button onClick={() => setActiveTab('trends')} className={getNavClass('trends')}>
              <TrendingUp size={18} /> Trends
            </button>
            <button onClick={() => setActiveTab('brainstorm')} className={getNavClass('brainstorm')}>
              <Lightbulb size={18} /> Brainstorm
            </button>
          </nav>

          <div className="p-4 border-t border-border bg-black/20">
            <div className="flex items-center gap-2 text-xs text-muted">
              <div className="w-2 h-2 rounded-full bg-green-500 shadow-[0_0_8px_rgba(34,197,94,0.6)]"></div>
              Core Online: localhost:8000
            </div>
          </div>
        </aside>
      )}

      {/* MAIN CONTENT AREA */}
      {/* flex-1 = занимай ВСЁ оставшееся пространство (растянись вправо) */}
      {/* flex + flex-col = чтобы внутри контент (ProjectDetail) тоже мог растягиваться по высоте */}
      {/* min-w-0 = критически важно для flex-контейнеров, чтобы контент не вылезал */}
      <main className="flex-1 flex flex-col h-full relative overflow-hidden min-w-0">

        {/* Фоновый градиент только на дашборде */}
        {!selectedProject && (
          <div className="absolute top-0 left-0 w-full h-96 bg-accent/5 rounded-full blur-3xl -translate-y-1/2 pointer-events-none"></div>
        )}

        {/* Само содержимое (Library, Projects или Detail) */}
        {renderContent()}

      </main>
    </div>
  );
}

export default App;
