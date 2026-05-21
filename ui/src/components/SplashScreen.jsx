import React from 'react';
import { WifiOff, RotateCw } from 'lucide-react';

export function SplashScreen({ status, onRetry }) {
  const isOffline = status === 'offline';

  return (
    <div className="fixed inset-0 z-50 flex flex-col items-center justify-center bg-background text-white select-none overflow-hidden">
      <div className="absolute inset-0 bg-[linear-gradient(180deg,rgba(24,24,27,0.62)_0%,rgba(9,9,11,0)_34%,rgba(9,9,11,0.9)_100%)]"></div>
      <div className="absolute inset-0 opacity-[0.025] [background-image:linear-gradient(rgba(255,255,255,0.9)_1px,transparent_1px),linear-gradient(90deg,rgba(255,255,255,0.9)_1px,transparent_1px)] [background-size:44px_44px]"></div>

      <div className="relative z-10 flex w-full max-w-[360px] flex-col items-center px-8">
        <div className="relative">
          <div className={`grid h-28 w-28 place-items-center overflow-hidden rounded-[28px] border bg-white shadow-[0_24px_80px_rgba(0,0,0,0.38)] transition-all duration-300 ${isOffline ? 'border-red-400/30 grayscale' : 'border-white/10'}`}>
            <img
              src="/app-icon.png"
              alt="Sculptor Pro"
              className="h-full w-full object-cover"
            />
          </div>

          {isOffline && (
            <div className="absolute -bottom-2 -right-2 grid h-9 w-9 place-items-center rounded-full border border-red-300/30 bg-red-500/95 text-white shadow-[0_12px_36px_rgba(239,68,68,0.22)]">
              <WifiOff size={17} />
            </div>
          )}
        </div>

        <div className="mt-10 w-full text-center">
          <h1 className="text-xl font-semibold tracking-[0.18em] text-white/95">
            SCULPTOR PRO
          </h1>
          <p className={`mt-3 text-xs font-medium uppercase tracking-[0.16em] transition-colors duration-300 ${isOffline ? 'text-red-300' : 'text-white/[0.48]'}`}>
            {isOffline ? 'Connection paused' : 'Preparing workspace'}
          </p>
        </div>

        <div className="mt-8 w-full">
          <div className={`splash-progress h-1 overflow-hidden rounded-full border ${isOffline ? 'border-red-400/[0.15] bg-red-950/30' : 'border-white/[0.08] bg-white/[0.055]'}`}>
            <div className={isOffline ? 'h-full w-1/3 rounded-full bg-red-400/70' : 'splash-progress__bar'}></div>
          </div>
        </div>

        {isOffline && (
          <div className="mt-7 text-center animate-in slide-in-from-bottom-2 duration-300">
            <p className="mx-auto mb-4 max-w-[280px] text-xs leading-5 text-muted/65">
              Access to neural networks and TMDB requires an active internet connection.
            </p>
            <button
              onClick={onRetry}
              className="group inline-flex items-center gap-2 rounded-lg border border-accent/20 bg-accent/10 px-5 py-2.5 text-sm font-medium text-accent shadow-[0_14px_40px_rgba(59,130,246,0.08)] transition-all duration-200 hover:border-accent/35 hover:bg-accent/15 hover:text-blue-300"
            >
              <RotateCw size={15} className="group-active:animate-spin" />
              Retry connection
            </button>
          </div>
        )}
      </div>
    </div>
  );
}
