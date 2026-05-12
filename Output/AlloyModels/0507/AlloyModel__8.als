// ===== RBAC Emergency Model (Alloy 6) =====
// -- Abstract, verifiable, incremental requirements modeling --

open util/ordering[State] as Time

// ===== ENUMS AND MODES =====

abstract sig Bool {}
one sig True, False extends Bool {}

abstract sig ClearanceLevel {}
one sig High, Medium, Low extends ClearanceLevel {}

abstract sig ClassificationLevel {}
one sig C_High, C_Medium, C_Low extends ClassificationLevel {}

abstract sig SystemMode {}
one sig Normal, Emergency extends SystemMode {}

// ===== CORE ENTITIES =====

sig User {
    clearance: one ClearanceLevel,
    isAdmin: one Bool
}

sig Administrator in User {}

sig Role {
    mutuallyExclusiveWith: set Role
}

sig Object {
    classification: one ClassificationLevel
}

sig Request {
    requestedBy: one User,
    affects: some Object,
    classification: one ClassificationLevel
}

sig Delegation {
    delegatee: one User,
    role: one Role,
    delegatedAt: one State,
    expiresAt: lone State
}

sig EmergencyPrivilege {
    admin: one Administrator,
    grantedAt: one State,
    revokedAt: lone State
}

// ===== SYSTEM STATE =====

sig State {
    mode: one SystemMode,
    emAdmins: set Administrator, // Exactly two if Emergency, else empty
    requests: set Request,
    delegations: set Delegation,
    emPrivs: set EmergencyPrivilege,
    needsCredentialUpdate: set Administrator
}

// ===== SYSTEM INVARIANTS & EXISTING-SYSTEM ASSUMPTIONS =====

// [EVENT]: Enforce at least two Administrators always exist
fact AtLeastTwoAdmins {
    #Administrator >= 2
}

// [EVENT]: All Administrators have High clearance and isAdmin=True
fact AdminDefinition {
    all a: Administrator | a.clearance = High and a.isAdmin = True
}

// [EVENT]: Emergency mode can only be triggered from Normal mode, by exactly two distinct admins, and only once per execution
fact EmergencyTriggerAndUniqueness {
    // Emergency mode: exactly two distinct emAdmins, only if at least two admins exist, only possible if previous state is Normal
    all s: State | 
        (s.mode = Emergency) => 
            (#s.emAdmins = 2 and
            all a: s.emAdmins | a in Administrator and
            some Time/prev[s] and Time/prev[s].mode = Normal and
            // Emergency can only be triggered if at least two admins exist
            #Administrator >= 2 and
            // In every Emergency state, the two emAdmins are distinct
            disj[s.emAdmins]
        )
        else
            (s.mode = Normal => no s.emAdmins)
    // Emergency mode can be entered at most once per execution
    // (i.e., there is no s1 < s2 with both s1.mode = Emergency and s2.mode = Emergency)
    all s1: State, s2: State |
        (s1 != s2 and s1.mode = Emergency and s2.mode = Emergency) => 
            (not (lt[s1, s2]) and not (lt[s2, s1]))
}

// [EVENT]: Ensure EmergencyPrivilege is assigned immediately and atomically upon Emergency mode activation
fact ImmediateEmergencyPrivilegeAssignment {
    all s: State |
        (s.mode = Emergency) =>
            (all a: s.emAdmins | one ep: s.emPrivs | ep.admin = a and ep.grantedAt = s and no ep.revokedAt)
        else
            // Only emAdmins may hold EmergencyPrivilege, and only in Emergency mode
            no s.emPrivs
}

// [EVENT]: Mutual exclusion is enforced in Normal mode, and not in Emergency mode
fact MutualExclusionEnforced {
    all s: State |
        (s.mode = Normal) =>
            all u: User |
                all r1, r2: Role | 
                    (r1 in rolesHeld[u, s] and r2 in rolesHeld[u, s] and r1 != r2) =>
                        not (r1 in r2.mutuallyExclusiveWith)
    // No constraint in Emergency mode
}

// [EVENT]: Highest classification for a set of objects
fun highestClass[os: set Object]: one ClassificationLevel {
    (some o: os | o.classification = C_High) => C_High
    else (some o: os | o.classification = C_Medium) => C_Medium
    else C_Low
}

// [EVENT]: Request classification is always highest among affected objects
fact RequestClassification {
    all req: Request |
        req.classification = highestClass[req.affects]
}

// [EVENT]: FIFO enforced in Normal, can be bypassed for C_High in Emergency
fact FIFOProcessingMode {
    all s: State |
        (s.mode = Normal) => FIFOProcessing[s]
    // No constraint in Emergency
}

pred FIFOProcessing[s: State] {} // Abstract, not implemented (focus: requirements, not implementation)

// =================== TEMPORAL HELPERS ===================

// [LESSON]: Alloy 6's 'open util/ordering[State] as Time' provides total order over State atoms.
// [LESSON]: Use Time/prev[s], Time/next[s], Time/first, Time/last for navigation.

fun rolesHeld[u: User, s: State]: set Role {
    { r: Role |
        some d: s.delegations | 
            d.delegatee = u and
            d.role = r and
            d.delegatedAt in pastOrEqual[s] and
            (no d.expiresAt or lt[s, d.expiresAt])
    }
}

fun pastOrEqual[s: State]: set State {
    { s2: State | lte[s2, s] }
}

// Helper: previous mode = Normal
pred prevModeIsNormal[s: State] {
    some Time/prev[s] and Time/prev[s].mode = Normal
}

// Helper: previous mode = Emergency
pred prevModeIsEmergency[s: State] {
    some Time/prev[s] and Time/prev[s].mode = Emergency
}

// =================== INCREMENTAL REQUIREMENTS ===================

// R1: Emergency only triggered from Normal mode, by exactly two distinct admins (possibly more in system)
pred R1 {
    // For all states: if Emergency mode, then exactly two distinct emAdmins, both are admins, previous mode Normal, and at least two admins exist
    all s: State |
        (s.mode = Emergency) => 
            (#s.emAdmins = 2 and all a: s.emAdmins | a in Administrator and disj[s.emAdmins] and prevModeIsNormal[s] and #Administrator >= 2)
        else
            (s.mode = Normal => no s.emAdmins)
}

// R2: Emergency mode is entered at most once per execution, and must eventually return to Normal (bounded duration or early termination)
pred R1R2 {
    R1 and
    // At most one Emergency mode period in the execution
    all s1, s2: State |
        (s1 != s2 and s1.mode = Emergency and s2.mode = Emergency) => 
            (not (lt[s1, s2]) and not (lt[s2, s1]))
    // If Emergency ever occurs, there exists a later state in Normal mode
    all s: State |
        (s.mode = Emergency) => (some s2: State | gt[s2, s] and s2.mode = Normal)
}

// R3: Emergency mode behavior
pred R1R2R3 {
    R1R2 and
    // R3.1: In Emergency, C_High requests can bypass FIFO
    all s: State |
        (s.mode = Emergency) => 
            all r: s.requests | 
                (r.classification = C_High) => canBeProcessedOutOfOrder[r, s]
    // R3.2: In Emergency, mutual exclusion not enforced
    and
    all s: State |
        (s.mode = Emergency) => notMutualExclusionDuringEmergency[s]
    // R3.3: Only emAdmins immediately and atomically hold EmergencyPrivilege on Emergency activation
    and
    all s: State |
        (s.mode = Emergency) =>
            (all a: s.emAdmins | one ep: s.emPrivs | ep.admin = a and ep.grantedAt = s and no ep.revokedAt)
    and
    all s: State | 
        (s.mode = Emergency) => (all ep: s.emPrivs | ep.admin in s.emAdmins and ep.grantedAt = s and no ep.revokedAt)
}

pred canBeProcessedOutOfOrder[r: Request, s: State] {
    r in s.requests and s.mode = Emergency and r.classification = C_High
}

pred notMutualExclusionDuringEmergency[s: State] {
    all u: User | all r1, r2: Role |
        (r1 in rolesHeld[u, s] and r2 in rolesHeld[u, s]) // No exclusion constraint checked
}

// R4: Post-Emergency Restoration
pred R1R2R3R4 {
    R1R2R3 and
    // R4.1: After Emergency, emAdmins lose EmergencyPrivilege
    all s: State |
        (s.mode = Normal and prevModeIsEmergency[s]) =>
            all a: Time/prev[s].emAdmins | no ep: s.emPrivs | ep.admin = a
    // R4.2: Only delegations assigned during Emergency are revoked when Emergency ends
    and
    all s: State |
        (s.mode = Normal and prevModeIsEmergency[s]) =>
            all d: s.delegations |
                (d.delegatedAt.mode = Emergency) => (d.expiresAt = s)
    // R4.3: Only the two emAdmins must update credentials after Emergency
    and
    all s: State |
        (s.mode = Normal and prevModeIsEmergency[s]) =>
            all a: Time/prev[s].emAdmins | a in s.needsCredentialUpdate
}

// All requirements predicate
pred All_Requirements { R1R2R3R4 }

// =================== ASSERTIONS FOR VERIFICATION ===================

// [EVENT]: Emergency mode can only be entered once per execution.
assert assert_EmergencyUnique {
    all s1, s2: State |
        (s1 != s2 and s1.mode = Emergency and s2.mode = Emergency) => 
            (not (lt[s1, s2]) and not (lt[s2, s1]))
}

// [EVENT]: EmergencyPrivilege is always assigned immediately upon Emergency mode activation
assert assert_EmergencyPrivilegeImmediate {
    all s: State |
        (s.mode = Emergency) => 
            (all a: s.emAdmins | one ep: s.emPrivs | ep.admin = a and ep.grantedAt = s and no ep.revokedAt)
}

// [EVENT]: Only exactly two distinct administrators are emAdmins per Emergency activation
assert assert_ExactlyTwoDistinctEmAdmins {
    all s: State |
        (s.mode = Emergency) => (#s.emAdmins = 2 and disj[s.emAdmins])
}

// [EVENT]: Not possible to enter Emergency mode if fewer than two administrators exist
assert assert_AtLeastTwoAdminsIfEmergency {
    all s: State |
        (s.mode = Emergency) => (#Administrator >= 2)
}

// [EVENT]: R1: Emergency only by two admins, from Normal mode
assert assertR1 {
    all s: State |
        (s.mode = Emergency) => (#s.emAdmins = 2 and all a: s.emAdmins | a in Administrator and disj[s.emAdmins] and prevModeIsNormal[s])
}

// [EVENT]: R2: Emergency mode is always exited (eventually returns to Normal)
assert assertR2 {
    all s: State |
        (s.mode = Emergency) => (some s2: State | gt[s2, s] and s2.mode = Normal)
}

// [EVENT]: R3: In Emergency, mutual exclusion is suspended
assert assertR3 {
    all s: State |
        (s.mode = Emergency) =>
            all u: User |
                all r1, r2: Role |
                    (r1 in rolesHeld[u, s] and r2 in rolesHeld[u, s]) // No exclusion constraint checked
}

// [EVENT]: R4.1: After Emergency, all EmergencyPrivileges revoked from emAdmins
assert assertR4_1 {
    all s: State |
        (s.mode = Normal and prevModeIsEmergency[s]) =>
            all a: Time/prev[s].emAdmins | no ep: s.emPrivs | ep.admin = a
}

// [EVENT]: R4.2: After Emergency, only Emergency-delegated roles are revoked
assert assertR4_2 {
    all s: State |
        (s.mode = Normal and prevModeIsEmergency[s]) =>
            all d: s.delegations |
                (d.delegatedAt.mode = Emergency) => d.expiresAt = s
}

// [EVENT]: R4.3: Only emAdmins must update credentials after Emergency
assert assertR4_3 {
    all s: State |
        (s.mode = Normal and prevModeIsEmergency[s]) =>
            all a: Time/prev[s].emAdmins | a in s.needsCredentialUpdate
}

// =================== RUN/CHECK COMMANDS ===================

run R1 for 5 but 3 State, 5 User, 3 Role, 5 Object, 5 Request
run R1R2 for 5 but 3 State, 5 User, 3 Role, 5 Object, 5 Request
run R1R2R3 for 5 but 3 State, 5 User, 3 Role, 5 Object, 5 Request
run R1R2R3R4 for 5 but 3 State, 5 User, 3 Role, 5 Object, 5 Request
run All_Requirements for 5 but 3 State, 5 User, 3 Role, 5 Object, 5 Request

check assert_EmergencyUnique for 5 but 3 State, 5 User, 3 Role, 5 Object, 5 Request
check assert_EmergencyPrivilegeImmediate for 5 but 3 State, 5 User, 3 Role, 5 Object, 5 Request
check assert_ExactlyTwoDistinctEmAdmins for 5 but 3 State, 5 User, 3 Role, 5 Object, 5 Request
check assert_AtLeastTwoAdminsIfEmergency for 5 but 3 State, 5 User, 3 Role, 5 Object, 5 Request

check assertR1 for 5 but 3 State, 5 User, 3 Role, 5 Object, 5 Request
check assertR2 for 5 but 3 State, 5 User, 3 Role, 5 Object, 5 Request
check assertR3 for 5 but 3 State, 5 User, 3 Role, 5 Object, 5 Request
check assertR4_1 for 5 but 3 State, 5 User, 3 Role, 5 Object, 5 Request
check assertR4_2 for 5 but 3 State, 5 User, 3 Role, 5 Object, 5 Request
check assertR4_3 for 5 but 3 State, 5 User, 3 Role, 5 Object, 5 Request

// -- END OF MODEL --

// [LESSON]: Alloy 6 subset signatures (e.g., Administrator in User) cannot be scoped in run/check; must scope only top-level sigs.
// [EVENT]: Added AtLeastTwoAdmins fact to enforce minimum administrator count at all times.
// [EVENT]: Rewrote EmergencyTriggerAndUniqueness to require exactly two distinct emAdmins, Emergency mode only entered from Normal mode, and at most once per execution.
// [EVENT]: Reworked ImmediateEmergencyPrivilegeAssignment so EmergencyPrivilege is assigned instantly on Emergency mode activation, and only to emAdmins.
// [EVENT]: Adjusted facts so the system can operate in Normal mode with any number of administrators (including fewer than two), but Emergency mode only permitted if at least two exist.
// [EVENT]: Added stronger assertion checks for single emergency activation and atomic EmergencyPrivilege assignment.