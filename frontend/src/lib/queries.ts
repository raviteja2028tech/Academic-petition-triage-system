import { useQuery } from "@tanstack/react-query";
import { api } from "./api";
import { isTerminal } from "./utils";

/** Polls every 2 s while the AI pipeline is still working, then stops. */
export function useRun(id: string | undefined) {
  return useQuery({
    queryKey: ["run", id],
    queryFn: () => api.run(id!),
    enabled: !!id,
    refetchInterval: (q) => (q.state.data && isTerminal(q.state.data.status) ? false : 2000),
  });
}
