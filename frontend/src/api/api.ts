import { UserInfo, ConversationRequest, Conversation, ChatMessage, CosmosDBHealth, CosmosDBStatus, IceToken } from "./models";
import { chatHistorySampleData } from "../constants/chatHistory";
import uuid from "react-uuid";

export async function avatarApi(message: ChatMessage,abortSignal: AbortSignal):Promise<Response> {
    const csrftoken = await getCSRFToken()
    const response = await fetch("/api/generate/avatar/", {
        method: "POST",
        headers: {
            'Content-Type': 'application/json',
            'X-CSRFToken': csrftoken
        },
        body: JSON.stringify(message),
        signal: abortSignal
    });

    return response;
}

export async function conversationApi(options: ConversationRequest, abortSignal: AbortSignal): Promise<Response> {
    const csrftoken = await getCSRFToken()
    const response = await fetch("/api/conversation/", {
        method: "POST",
        headers: {
            'Content-Type': 'application/json',
            'X-CSRFToken': csrftoken
        },
        body: JSON.stringify({
            messages: options.messages
        }),
        signal: abortSignal
    });

    return response;
}

export async function getCSRFTokenBackend(){
    const response = await fetch('/api/.get-csrf-token/',{method: "GET"});
    if (response.ok) {
        const result = await response.json();
        return result.csrfToken
    }
    else {
        throw new Error(`Failed fetching csrf-token: ${response.status} ${response.statusText}`)
    }
}

export async function getCSRFToken() {
    let csrfToken = null;
    const cookies = document.cookie.split(';');
    for (let cookie of cookies) {
        const [name, value] = cookie.trim().split('=');
        if (name === 'csrftoken') {
            csrfToken = value;
            break;
        }
    }
    if(csrfToken === null)
        csrfToken = await getCSRFTokenBackend()
    return csrfToken;
}

export async function getIceToken(): Promise<IceToken> {
    const response = await fetch('/api/getIceToken/');
    if (response.ok) {
        const payload = await response.json();
        return payload;
    }
    else {
        throw new Error(`Failed fetching ICE token: ${response.status} ${response.statusText}`)
    }
}

export async function connectAvatar(localSdp: any, clientId: string): Promise<Response> {
    const csrftoken = await getCSRFToken()
    const response = await fetch('/api/connectAvatar/', {
        method: 'POST',
        headers: {
            'ClientId': clientId,
            'X-CSRFToken': csrftoken
        },
        body: localSdp
    })
    return response
}
// Do HTML encoding on given text
export function htmlEncode(text: string): string {
    const entityMap: { [key: string]: string } = {
        '&': '&amp;',
        '<': '&lt;',
        '>': '&gt;',
        '"': '&quot;',
        "'": '&#39;',
        '/': '&#x2F;'
    };

    return String(text).replace(/[&<>"'\/]/g, (match) => entityMap[match])
}

export async function PostSpeak(spokenText: string, clientId: string) {
    console.log("[" + (new Date()).toISOString() + "] Speak request sent.")
    const csrftoken = await getCSRFToken()
    const response = await fetch('/api/speak/', {
        method: 'POST',
        headers: {
            'ClientId': clientId,
            'X-CSRFToken': csrftoken,
            'Content-Type': 'application/ssml+xml'
        },
        body: spokenText
    });
    if (response.ok) {
        response.text().then(text => {
            console.log(`[${new Date().toISOString()}] Speech synthesized to speaker for text [ ${spokenText} ]. Result ID: ${text}`)
        })
    } 
    else {
        throw new Error(`[${new Date().toISOString()}] Unable to speak text. ${response.status} ${response.statusText}`)
    }
}

export async function getUserInfo(): Promise<UserInfo[]> {
    const response = await fetch('/api/.auth/me/');
    if (!response.ok) {
        console.log("No identity provider found. Access to chat will be blocked.")
        return [];
    }

    const payload = await response.json();
    return payload;
}

export const fetchChatHistoryInit = async (): Promise<Conversation[] | null> => {
// export const fetchChatHistoryInit = (): Conversation[] | null => {
    // Make initial API call here

    return null;
    // return chatHistorySampleData;
}

export const historyList = async (): Promise<Conversation[] | null> => {
    const response = await fetch("/api/history/list/", {
        method: "GET",
    }).then(async (res) => {
        const payload = await res.json();
        if (!Array.isArray(payload)) {
            console.error("There was an issue fetching your data.");
            return null;
        }
        const conversations: Conversation[] = await Promise.all(payload.map(async (conv: any) => {
            let convMessages: ChatMessage[] = [];
            convMessages = await historyRead(conv.id)
            .then((res) => {
                return res
            })
            .catch((err) => {
                console.error("error fetching messages: ", err)
                return []
            })
            const conversation: Conversation = {
                id: conv.id,
                title: conv.title,
                date: conv.createdAt,
                messages: convMessages
            };
            return conversation;
        }));
        return conversations;
    }).catch((err) => {
        console.error("There was an issue fetching your data.");
        return null
    })

    return response
}

export const historyRead = async (convId: string): Promise<ChatMessage[]> => {
    const csrftoken = await getCSRFToken()
    const response = await fetch("/api/history/read/", {
        method: "POST",
        body: JSON.stringify({
            conversation_id: convId
        }),
        headers: {
            'X-CSRFToken': csrftoken,
            "Content-Type": "application/json"
        },
    })
    .then(async (res) => {
        if(!res){
            return []
        }
        const payload = await res.json();
        let messages: ChatMessage[] = [];
        if(payload?.messages){
            payload.messages.forEach((msg: any) => {
                const message: ChatMessage = {
                    id: msg.id,
                    role: msg.role,
                    date: msg.createdAt,
                    content: msg.content,
                }
                messages.push(message)
            });
        }
        return messages;
    }).catch((err) => {
        console.error("There was an issue fetching your data.");
        return []
    })
    return response
}

export const historyGenerate = async (options: ConversationRequest, abortSignal: AbortSignal, convId?: string): Promise<Response> => {
    let body;
    if(convId){
        body = JSON.stringify({
            conversation_id: convId,
            messages: options.messages
        })
    }else{
        body = JSON.stringify({
            messages: options.messages
        })
    }
    const csrftoken = await getCSRFToken()
    const response = await fetch("/api/history/generate/", {
        method: "POST",
        headers: {
            'X-CSRFToken': csrftoken,
            "Content-Type": "application/json"
        },
        body: body,
        signal: abortSignal
    }).then((res) => {
        return res
    })
    .catch((err) => {
        console.error("There was an issue fetching your data.");
        return new Response;
    })
    return response
}

export const historyUpdate = async (messages: ChatMessage[], convId: string): Promise<Response> => {
    const csrftoken = await getCSRFToken()
    const response = await fetch("/api/history/update/", {
        method: "POST",
        body: JSON.stringify({
            conversation_id: convId,
            messages: messages
        }),
        headers: {
            'X-CSRFToken': csrftoken,
            "Content-Type": "application/json"
        },
    }).then(async (res) => {
        return res
    })
    .catch((err) => {
        console.error("There was an issue fetching your data.");
        let errRes: Response = {
            ...new Response,
            ok: false,
            status: 500,
        }
        return errRes;
    })
    return response
}

export const historyDelete = async (convId: string) : Promise<Response> => {
    const csrftoken = await getCSRFToken()
    const response = await fetch("/api/history/delete/", {
        method: "DELETE",
        body: JSON.stringify({
            conversation_id: convId,
        }),
        headers: {
            'X-CSRFToken': csrftoken,
            "Content-Type": "application/json"
        },
    })
    .then((res) => {
        return res
    })
    .catch((err) => {
        console.error("There was an issue fetching your data.");
        let errRes: Response = {
            ...new Response,
            ok: false,
            status: 500,
        }
        return errRes;
    })
    return response;
}

export const historyDeleteAll = async () : Promise<Response> => {
    const csrftoken = await getCSRFToken()
    const response = await fetch("/api/history/delete_all/", {
        method: "DELETE",
        body: JSON.stringify({}),
        headers: {
            'X-CSRFToken': csrftoken,
            "Content-Type": "application/json"
        },
    })
    .then((res) => {
        return res
    })
    .catch((err) => {
        console.error("There was an issue fetching your data.");
        let errRes: Response = {
            ...new Response,
            ok: false,
            status: 500,
        }
        return errRes;
    })
    return response;
}

export const historyClear = async (convId: string) : Promise<Response> => {
    const csrftoken = await getCSRFToken()
    const response = await fetch("/api/history/clear/", {
        method: "POST",
        body: JSON.stringify({
            conversation_id: convId,
        }),
        headers: {
            'X-CSRFToken': csrftoken,
            "Content-Type": "application/json"
        },
    })
    .then((res) => {
        return res
    })
    .catch((err) => {
        console.error("There was an issue fetching your data.");
        let errRes: Response = {
            ...new Response,
            ok: false,
            status: 500,
        }
        return errRes;
    })
    return response;
}

export const historyRename = async (convId: string, title: string) : Promise<Response> => {
    const csrftoken = await getCSRFToken()
    const response = await fetch("/api/history/rename/", {
        method: "POST",
        body: JSON.stringify({
            conversation_id: convId,
            title: title
        }),
        headers: {
            'X-CSRFToken': csrftoken,
            "Content-Type": "application/json"
        },
    })
    .then((res) => {
        return res
    })
    .catch((err) => {
        console.error("There was an issue fetching your data.");
        let errRes: Response = {
            ...new Response,
            ok: false,
            status: 500,
        }
        return errRes;
    })
    return response;
}

export const historyEnsure = async (): Promise<CosmosDBHealth> => {
    const response = await fetch("/api/history/ensure/", {
        method: "GET",
    })
    .then(async res => {
        let respJson = await res.json();
        let formattedResponse;
        if(respJson.message){
            formattedResponse = CosmosDBStatus.Working
        }else{
            if(res.status === 500){
                formattedResponse = CosmosDBStatus.NotWorking
            }else{
                formattedResponse = CosmosDBStatus.NotConfigured
            }
        }
        if(!res.ok){
            return {
                cosmosDB: false,
                status: formattedResponse
            }
        }else{
            return {
                cosmosDB: true,
                status: formattedResponse
            }
        }
    })
    .catch((err) => {
        console.error("There was an issue fetching your data.");
        return {
            cosmosDB: false,
            status: err
        }
    })
    return response;
}

