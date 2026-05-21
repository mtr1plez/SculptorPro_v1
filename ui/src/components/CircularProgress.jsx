import { useEffect, useState } from 'react';

export function CircularProgress({ percent, size = 60, strokeWidth = 4 }) {
  const [displayPercent, setDisplayPercent] = useState(percent);

  // === ЛОГИКА ПЛАВНОЙ ПРОКРУТКИ ЦИФР ===
  useEffect(() => {
    // Если пришло то же самое число, ничего не делаем
    if (percent === displayPercent) return;

    // Вычисляем шаг. Если разрыв большой (0->80), бежим быстрее.
    // Если маленький (10->11), бежим по единичке.
    const diff = percent - displayPercent;
    const step = diff > 0 ? 1 : -1;
    const delay = Math.max(5, 500 / Math.abs(diff)); // 500мс на всю анимацию макс

    const timer = setTimeout(() => {
      setDisplayPercent(prev => prev + step);
    }, delay);

    return () => clearTimeout(timer);
  }, [percent, displayPercent]);

  // Параметры для SVG
  const radius = (size - strokeWidth) / 2;
  const circumference = radius * 2 * Math.PI;
  // Делаем фиксированный "хвостик" (например, 75% длины окружности), 
  // который будет просто крутиться
  const spinnerOffset = circumference * 0.25; 

  return (
    <div className="relative flex items-center justify-center" style={{ width: size, height: size }}>
      
      {/* 1. ВРАЩАЮЩИЙСЯ КРУГ (SPINNER) */}
      <svg 
        className="absolute inset-0 w-full h-full animate-spin duration-[1.5s]" 
        viewBox={`0 0 ${size} ${size}`}
      >
        {/* Фоновый серый круг (трек) */}
        <circle
          className="text-zinc-800"
          strokeWidth={strokeWidth}
          stroke="currentColor"
          fill="transparent"
          r={radius}
          cx={size / 2}
          cy={size / 2}
        />
        {/* Активный синий "хвостик" */}
        <circle
          className="text-accent drop-shadow-[0_0_4px_rgba(59,130,246,0.8)]"
          strokeWidth={strokeWidth}
          strokeDasharray={circumference}
          strokeDashoffset={spinnerOffset}
          strokeLinecap="round"
          stroke="currentColor"
          fill="transparent"
          r={radius}
          cx={size / 2}
          cy={size / 2}
        />
      </svg>

      {/* 2. ЦИФРЫ В ЦЕНТРЕ (Не вращаются) */}
      <span className="relative text-xs font-bold text-white font-mono z-10">
        {displayPercent}%
      </span>
    </div>
  );
}