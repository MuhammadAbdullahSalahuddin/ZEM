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

        const rotX = ((y - centerY) / centerY) * -maxTilt;
        const rotY = ((x - centerX) / centerX) * maxTilt;
        const shadowX = -rotY * 1.5;
        const shadowY = rotX * 1.5;

        card.style.transform = `rotateX(${rotX.toFixed(2)}deg) rotateY(${rotY.toFixed(2)}deg) scale3d(1.015, 1.015, 1.015)`;
        card.style.boxShadow = `${shadowX.toFixed(1)}px ${shadowY.toFixed(1)}px 35px rgba(0, 0, 0, 0.9), 0 0 2px 1px rgba(255, 255, 255, 0.2)`;
        card.style.transition = 'transform 0.05s ease-out, box-shadow 0.05s ease-out';

        if (glare) {
          glare.style.opacity = '0.22';
          glare.style.background = `radial-gradient(circle 420px at ${(x / rect.width) * 100}% ${(y / rect.height) * 100}%, rgba(255, 255, 255, 0.35), transparent 70%)`;
        }
      });
    };

    const handleMouseLeave = () => {
      cancelAnimationFrame(rafId);
      card.style.transform = 'rotateX(0deg) rotateY(0deg) scale3d(1, 1, 1)';
      card.style.boxShadow = '0 20px 40px -15px rgba(0, 0, 0, 0.9), 0 0 1px 1px rgba(255, 255, 255, 0.1)';
      card.style.transition = 'transform 0.4s cubic-bezier(0.16, 1, 0.3, 1), box-shadow 0.4s cubic-bezier(0.16, 1, 0.3, 1)';
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

  return (
    <div
      ref={containerRef}
      className="relative w-full h-full"
      style={{
        perspective: '1000px',
        ...style,
      }}
      {...props}
    >
      <div
        ref={cardRef}
        className={`w-full h-full relative ${className}`}
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
