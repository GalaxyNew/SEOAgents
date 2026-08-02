import { useEffect, useState } from 'react'

/** 窄屏判定 —— 移动端布局的唯一开关,避免各组件各写一套阈值。 */
export function useIsMobile(breakpoint = 820): boolean {
  const [isMobile, setIsMobile] = useState<boolean>(
    typeof window !== 'undefined' ? window.innerWidth < breakpoint : false
  )
  useEffect(() => {
    const onResize = () => setIsMobile(window.innerWidth < breakpoint)
    window.addEventListener('resize', onResize)
    onResize()
    return () => window.removeEventListener('resize', onResize)
  }, [breakpoint])
  return isMobile
}
