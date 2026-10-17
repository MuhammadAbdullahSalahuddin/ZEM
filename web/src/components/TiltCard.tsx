import React, { useRef, useEffect } from 'react';

interface TiltCardProps extends React.HTMLAttributes<HTMLDivElement> {
  children: React.ReactNode;
  className?: string;
  maxTilt?: number;
}

export function TiltCard({
  children,
  className = '',
  maxTilt = 12,
  style,
  ...props
}: TiltCardProps) {
  const containerRef = useRef<HTMLDivElement | null>(null);
  const cardRef = useRef<HTMLDivElement | null>(null);
  const glareRef = useRef<HTMLDivElement | null>(null);

  useEffect(() => {
    const container = containerRef.current;
    const card = cardRef.current;
    const glare = glareRef.current;
    if (!container || !card) return;

    let rafId: number;

    const handleMouseMove = (e: MouseEvent) => {
      cancelAnimationFrame(rafId);
      rafId = requestAnimationFrame(() => {
        const rect = container.getBoundingClientRect();
        const x = e.clientX - rect.left;
        const y = e.clientY - rect.top;
        const centerX = rect.width / 2;
        const centerY = rect.height / 2;

        // Ultra-subtle micro-depth (capped at 0.8 deg) with zero scale jump so text stays razor sharp
        const dampenedTilt = Math.min(maxTilt * 0.08, 0.8);
        const rotX = ((y - centerY) / centerY) * -dampenedTilt;
        const rotY = ((x - centerX) / centerX) * dampenedTilt;

        card.style.transform = `rotateX(${rotX.toFixed(2)}deg) rotateY(${rotY.toFixed(2)}deg)`;
        card.style.borderColor = 'rgba(255, 255, 255, 0.28)';
        card.style.transition = 'transform 0.12s ease-out, border-color 0.2s ease-out';

        if (glare) {
          glare.style.opacity = '0.07';
          glare.style.background = `radial-gradient(circle 480px at ${(x / rect.width) * 100}% ${(y / rect.height) * 100}%, rgba(56, 189, 248, 0.22), rgba(255, 255, 255, 0.08) 40%, transparent 75%)`;
        }
      });
    };

    const handleMouseLeave = () => {
      cancelAnimationFrame(rafId);
      card.style.transform = 'rotateX(0deg) rotateY(0deg)';
      card.style.borderColor = '';
      card.style.transition = 'transform 0.5s cubic-bezier(0.16, 1, 0.3, 1), border-color 0.3s ease-out';
      if (glare) {
        glare.style.opacity = '0';
      }
    };

    container.addEventListener('mousemove', handleMouseMove);
    container.addEventListener('mouseleave', handleMouseLeave);

    return () => {
      cancelAnimationFrame(rafId);
      container.removeEventListener('mousemove', handleMouseMove);
      container.removeEventListener('mouseleave', handleMouseLeave);
    };
  }, [maxTilt]);

  const wantsFullHeight = className.includes('h-full') || className.includes('flex-1');

  return (
    <div
      ref={containerRef}
      className={`relative w-full ${wantsFullHeight ? 'h-full flex-1 flex flex-col' : ''}`}
      style={{
        perspective: '1000px',
        ...style,
      }}
      {...props}
    >
      <div
        ref={cardRef}
        className={`w-full relative ${className}`}
        style={{
          transform: 'rotateX(0deg) rotateY(0deg) scale3d(1, 1, 1)',
          boxShadow: '0 20px 40px -15px rgba(0, 0, 0, 0.9), 0 0 1px 1px rgba(255, 255, 255, 0.1)',
        }}
      >
        {/* Specular lighting sheen tracking cursor */}
        <div
          ref={glareRef}
          className="pointer-events-none absolute inset-0 z-30 transition-opacity duration-300 rounded-[inherit]"
          style={{ opacity: 0 }}
        />

        {children}
      </div>
    </div>
  );
}
