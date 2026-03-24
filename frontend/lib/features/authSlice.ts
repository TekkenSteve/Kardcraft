import { createSlice, PayloadAction } from '@reduxjs/toolkit';

export interface AuthState {
  token: string | null;
  userId: string | null;
  name?: string | null;
  expiresAt?: string | null; // ISO string
}

const initialState: AuthState = {
  token: null,
  userId: null,
  name: null,
  expiresAt: null,
};

interface CredentialsPayload {
  token: string;
  userId: string;
  name?: string;
  expiresAt?: string; // ISO
}

interface ProfilePayload {
  userId: string | null;
  name?: string | null;
  expiresAt?: string | null; // ISO
}

export const authSlice = createSlice({
  name: 'auth',
  initialState,
  reducers: {
    setCredentials(state, action: PayloadAction<CredentialsPayload>) {
      const { token, userId, name, expiresAt } = action.payload;
      state.token = token;
      state.userId = userId;
      state.name = name ?? null;
      state.expiresAt = expiresAt ?? null;
    },
    setProfile(state, action: PayloadAction<ProfilePayload>) {
      const { userId, name, expiresAt } = action.payload;
      state.userId = userId;
      state.name = name ?? null;
      state.expiresAt = expiresAt ?? null;
    },
    clearCredentials(state) {
      state.token = null;
      state.userId = null;
      state.name = null;
      state.expiresAt = null;
    },
  },
});

export const { setCredentials, setProfile, clearCredentials } = authSlice.actions;
export default authSlice.reducer;
