import Link from 'next/link';
import { useRouter } from 'next/router';
import { PropsWithChildren, useState } from 'react';
import AutoGraphRoundedIcon from '@mui/icons-material/AutoGraphRounded';
import CollectionsBookmarkRoundedIcon from '@mui/icons-material/CollectionsBookmarkRounded';
import DashboardRoundedIcon from '@mui/icons-material/DashboardRounded';
import DeckRoundedIcon from '@mui/icons-material/DeckRounded';
import Inventory2RoundedIcon from '@mui/icons-material/Inventory2Rounded';
import LayersRoundedIcon from '@mui/icons-material/LayersRounded';
import MenuRoundedIcon from '@mui/icons-material/MenuRounded';
import StorageRoundedIcon from '@mui/icons-material/StorageRounded';
import SettingsRoundedIcon from '@mui/icons-material/SettingsRounded';
import SyncRoundedIcon from '@mui/icons-material/SyncRounded';
import {
  AppBar,
  Box,
  Chip,
  Divider,
  Drawer,
  IconButton,
  List,
  ListItemButton,
  ListItemIcon,
  ListItemText,
  Toolbar,
  Typography,
} from '@mui/material';

const navigation = [
  { href: '/', label: 'Dashboard', icon: <DashboardRoundedIcon /> },
  { href: '/cards', label: 'Karten', icon: <Inventory2RoundedIcon /> },
  { href: '/set-import', label: 'Set-Erfassung', icon: <LayersRoundedIcon /> },
  { href: '/storage-locations', label: 'Lagerorte', icon: <StorageRoundedIcon /> },
  { href: '/decks', label: 'Decklisten', icon: <DeckRoundedIcon /> },
  { href: '/collections', label: 'Sammlungen', icon: <CollectionsBookmarkRoundedIcon /> },
  { href: '/sync-status', label: 'Sync & Jobs', icon: <SyncRoundedIcon /> },
  { href: '/settings', label: 'Einstellungen', icon: <SettingsRoundedIcon /> },
];

const drawerWidth = 280;

export default function AppShell({ children }: PropsWithChildren) {
  const router = useRouter();
  const [mobileOpen, setMobileOpen] = useState(false);

  const drawer = (
    <Box sx={{ height: '100%', display: 'flex', flexDirection: 'column', p: 2.5 }}>
      <Box sx={{ mb: 3 }}>
        <Box
          sx={{
            width: 52,
            height: 52,
            borderRadius: '18px',
            background: 'linear-gradient(135deg, rgba(216,169,76,0.95), rgba(78,162,138,0.95))',
            display: 'grid',
            placeItems: 'center',
            boxShadow: '0 18px 40px rgba(216, 169, 76, 0.25)',
            mb: 1.5,
          }}
        >
          <AutoGraphRoundedIcon sx={{ color: '#091110' }} />
        </Box>
        <Typography variant="h5">YGO Sammlung</Typography>
        <Typography color="text.secondary" sx={{ mt: 0.75 }}>
          Verwaltung, Preise, Trends und lokale Assets in einem produktionsnahen MVP.
        </Typography>
      </Box>

      <Chip label="FastAPI + Next.js" color="secondary" variant="outlined" sx={{ alignSelf: 'flex-start', mb: 2.5 }} />

      <List sx={{ p: 0 }}>
        {navigation.map((item) => {
          const active = router.pathname === item.href || router.pathname.startsWith(`${item.href}/`);
          return (
            <ListItemButton
              key={item.href}
              component={Link}
              href={item.href}
              selected={active}
              sx={{
                borderRadius: 3,
                mb: 0.75,
                '&.Mui-selected': {
                  backgroundColor: 'rgba(216, 169, 76, 0.16)',
                },
              }}
              onClick={() => setMobileOpen(false)}
            >
              <ListItemIcon sx={{ color: active ? 'primary.main' : 'text.secondary', minWidth: 38 }}>{item.icon}</ListItemIcon>
              <ListItemText primary={item.label} />
            </ListItemButton>
          );
        })}
      </List>

      <Box sx={{ mt: 'auto', pt: 2.5 }}>
        <Divider sx={{ borderColor: 'rgba(255,255,255,0.08)', mb: 2 }} />
        <Typography variant="body2" color="text.secondary">
          Preis-Provider und Bildquellen bleiben austauschbar. Cardmarket und Omega sind sauber gekapselt.
        </Typography>
      </Box>
    </Box>
  );

  return (
    <Box sx={{ minHeight: '100vh', display: 'flex' }}>
      <AppBar
        position="fixed"
        color="transparent"
        sx={{
          display: { md: 'none' },
          backdropFilter: 'blur(16px)',
          boxShadow: 'none',
          borderBottom: '1px solid rgba(255,255,255,0.08)',
        }}
      >
        <Toolbar>
          <IconButton color="inherit" edge="start" onClick={() => setMobileOpen(true)}>
            <MenuRoundedIcon />
          </IconButton>
          <Typography variant="h6">YGO Sammlung</Typography>
        </Toolbar>
      </AppBar>

      <Box component="nav" sx={{ width: { md: drawerWidth }, flexShrink: { md: 0 } }}>
        <Drawer
          variant="temporary"
          open={mobileOpen}
          onClose={() => setMobileOpen(false)}
          ModalProps={{ keepMounted: true }}
          sx={{
            display: { xs: 'block', md: 'none' },
            '& .MuiDrawer-paper': { width: drawerWidth, bgcolor: 'background.paper' },
          }}
        >
          {drawer}
        </Drawer>
        <Drawer
          variant="permanent"
          sx={{
            display: { xs: 'none', md: 'block' },
            '& .MuiDrawer-paper': {
              width: drawerWidth,
              boxSizing: 'border-box',
              bgcolor: 'rgba(10, 18, 18, 0.92)',
              borderRight: '1px solid rgba(255,255,255,0.06)',
              backdropFilter: 'blur(16px)',
            },
          }}
          open
        >
          {drawer}
        </Drawer>
      </Box>

      <Box
        component="main"
        sx={{
          flexGrow: 1,
          px: { xs: 2, sm: 3, md: 4 },
          py: { xs: 10, md: 4 },
        }}
      >
        {children}
      </Box>
    </Box>
  );
}
