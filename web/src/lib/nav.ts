import { createContext, useContext } from 'react'

/** 窄屏时左侧阶段菜单是抽屉：顶栏的按钮打开，选中后自动关闭。 */
export const NavContext = createContext<{ open: boolean; setOpen: (open: boolean) => void }>({ open: false, setOpen: () => {} })

export const useNav = () => useContext(NavContext)
