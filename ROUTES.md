# UberNet routes (client build 45269)

Source: `MNCCore.HWebInterface` default `APICalls`, indexed by `EWebAPIType`. Placeholders are filled in by the client. Matchmaking also uses the hardcoded `/MM/Matchmake` and `/Message/GetMessages` (long poll, implemented).

| API | Path | Emulator |
|---|---|---|
| Info | `/GC/Info` | implemented |
| Login | `/GC/Authenticate` | implemented |
| CompleteRegistration | `/GC/CompleteRegistration` | acknowledged ({}) |
| Logout | `/GC/Logout` | acknowledged ({}) |
| UserInfo | `/GC/UserInfo/v2` | implemented |
| NetInfo | `/GC/NetInfo` | implemented |
| GetSteamFriendsList | `/GC/GetSteamFriendsList` | empty list |
| GetNews | `/GC/GetNews/1/10` | implemented |
| GetRecentGames | `/GC/GetRecentGames/v2?BuildVersion=%Version%&MaxResults=%MaxResults%` | empty list |
| GetReplay | `/GC/GetReplay/%Version%/%LobbyId%` | falls back to {} |
| GetPurchasableItems | `/GC/PurchasableItems/%Version%` | implemented |
| CreateCart | `/GameClient/CreateCart` | falls back to {} |
| InitiatePurchase | `/GameClient/InitiatePurchase` | falls back to {} |
| CompletePurchase | `/GameClient/CompletePurchase` | falls back to {} |
| UserInventory | `/GC/UserInventory` | implemented |
| GetProfile | `/GC/Profile` | implemented |
| PostProfile | `/GC/Profile/Update` | implemented |
| ClientGetStats | `/GC/Stats` | acknowledged ({}) |
| ServerPostStats | `/GS/%UserId%/Stats/Update` | acknowledged ({}) |
| ServerExpectedPlayerData | `/GS/ExpectedPlayerData` | acknowledged ({}) |
| ServerModifyVirtualCurrency | `/GS/ModifyVirtualCurrency` | acknowledged ({}) |
| ServerGrantItemsToUsers | `/GS/GrantItemsToUsers` | acknowledged ({}) |
| ServerReportPlayer | `/GS/ReportPlayer` | acknowledged ({}) |
| ServerPostGameResults | `/GS/PostGameResults` | acknowledged ({}) |
| ServerPlayerJoined | `/GameServer/RedeemGameTicket` | acknowledged ({}) |
| ServerPlayerLeft | `/GameServer/PlayerLeft` | acknowledged ({}) |
| ServerAwardSteamAchievement | `/GameServer/AwardSteamAchievement` | acknowledged ({}) |
| MonitorServerUp | `/MS/ServerUp` | acknowledged ({}) |
| MonitorServerDown | `/MS/ServerDown` | acknowledged ({}) |
| MonitorPlayerJoined | `/MS/%UserId%/PlayerJoined` | acknowledged ({}) |
| MonitorPlayerLeft | `/MS/%UserId%/PlayerLeft` | acknowledged ({}) |
| MonitorMatchBegin | `/MS/MatchBegin` | acknowledged ({}) |
| MonitorMatchEnd | `/MS/MatchEnd` | acknowledged ({}) |
| MonitorUpdateStatus | `/MS/UpdateStatus` | acknowledged ({}) |
| GASCreateGame | `/GAS/CreateGame` | falls back to {} |
| GASJoinGame | `/GAS/MatchmakeV2` | falls back to {} |
| GASRolloverGame | `/GAS/ServerMatchmakeV2` | falls back to {} |
| GASGetGameAddress | `/GAS/GetGameAddress/%LobbyId%` | falls back to {} |
| GASGetGameAddressAndTicket | `/GAS/GetGameAddressAndTicket/%LobbyId%` | falls back to {} |
| GASGetGameWithPlayer | `/GAS/GetGameWithPlayer/%SteamId%` | falls back to {} |
| GASRemovePlayerFromGame | `/GAS/RemovePlayerFromGame` | falls back to {} |
| GetMatchmakingRegionInfo | `/Matchmaking/GetMatchmakingRegionInfo?TitleId=%TitleId%&Version=%Version%` | implemented |
| RedeemCoupon | `/GC/RedeemCoupon` | falls back to {} |
| UnlockCrate | `/GC/UnlockCrate` | falls back to {} |
| RecycleItem | `/GC/RecycleItem` | falls back to {} |
| SubmitUserFeedback | `/GC/SubmitUserFeedback` | acknowledged ({}) |
| AddFriendTag | `/GC/AddFriendTag` | falls back to {} |
| RemoveFriendTag | `/GC/RemoveFriendTag` | falls back to {} |
| RenameFriend | `/GC/RenameFriend` | falls back to {} |
| GetUberFriendsList | `/GC/GetUberFriendsList` | empty list |
| LinkSteamRequest | `/GC/LinkSteamRequest` | falls back to {} |
| LinkKongregateRequest | `/GC/LinkKongregateAccount` | falls back to {} |
| G1Login | `/GC/GamersFirstLogin` | implemented |
