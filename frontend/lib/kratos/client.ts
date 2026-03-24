import { Configuration, FrontendApi } from "@ory/client"

const kratosConfig = {
  basePath: process.env.NEXT_PUBLIC_AUTH_BASE_PATH || "/auth",
  baseOptions: {
    withCredentials: true,
  },
}

export const ory = new FrontendApi(new Configuration(kratosConfig))

// Re-export types for convenience
export type {
  LoginFlow,
  RegistrationFlow,
  Session,
  UiNode,
  UpdateLoginFlowBody,
  UpdateRegistrationFlowBody,
} from "@ory/client"
