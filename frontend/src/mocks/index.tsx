/** 假資料層唯一入口（票 B2-library）。`main.tsx` 只 import 這一支檔案；切真後端時刪掉
 * 那一行 import ＋這整個目錄，app 程式碼不用跟著改一行。 */
import { createRoot } from "react-dom/client";
import { DevScenarioToggle } from "./DevToggle";
import "./handlers";
import "./productsHandlers";
import { installMockFetch } from "./network";

installMockFetch();

const container = document.createElement("div");
container.id = "library-mock-scenario-toggle-root";
document.body.appendChild(container);
createRoot(container).render(<DevScenarioToggle />);
