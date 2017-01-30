#!/usr/bin/env python

"""

personal_importRawKey


1) Generate key pairs:
   - Posting pair
   - Voting pair
   - Wallet pair
   - user_id is wallet address
2) User imports his keys into web node. / keys created upon signup.
3) 


A) Web node usually retains users' private keys (unless optionally imported / exported), HTTP cookies and passwords used for authentication.
B) User always retains his private keys, all signing is done before passing the messages to the Web node, no additional authentication used.

---

- generate user keys, store in external keystore
- sign all transactions off-chain, submit under sponsor's keys
- 

password.value

https://github.com/steemit/steemit.com/blob/ded8ecfcc9caf2d73b6ef12dbd0191bd9dbf990b/shared/ecc/test/KeyFormats.js

BEST:
https://github.com/steemit/steemit.com/blob/ded8ecfcc9caf2d73b6ef12dbd0191bd9dbf990b/app/redux/UserSaga.js#L109

-----
CCCoin dApp.

This version uses a single off-chain witness for minting and rewards distribution.
The witness can also be audited by anyone with this code and access to the blockchain.

Version 2 will replace the single auditable witness with:
- Comittee of witnesses that are voted on by token holders. The witnesses then vote on the rewards distribution.
- 100% on-chain rewards computation in smart contracts.

---- INSTALL:

#sudo add-apt-repository ppa:ethereum/ethereum
sudo add-apt-repository ppa:ethereum/ethereum-dev
sudo apt-get update

curl -sL https://deb.nodesource.com/setup_7.x | sudo -E bash -
sudo apt-get install -y nodejs

sudo npm install -g ethereumjs-testrpc

sudo npm install -g solc

sudo ln -s /usr/bin/nodejs /usr/bin/node

#pip install ethereum
#pip install ethereum-serpent

pip install py-solc
pip install ethjsonrpc

---- RUNNING:

testrpc -p 9999

python offchain.py deploy_dapp ## first time only
python offchain.py witness
python offchain.py web

---- GETH:

geth --fast --cache=1024 --rpc --testnet --datadir /datasets/ethereum_testnet


---- EXAMPLES:


"""


from os import mkdir, listdir, makedirs, walk, rename, unlink
from os.path import exists,join,split,realpath,splitext,dirname


## TODO - use database:

DATA_DIR = 'cccoin_conf/'
CONTRACT_ADDRESS_FN = DATA_DIR + 'cccoin_contract_address.txt'
USER_DB_FN = DATA_DIR + 'cccoin_users.json'


######## Primitive, single-process key store:

## TODO - use a KDF for extra protection of master password?

import getpass
from Crypto.Cipher import AES
from Crypto.Random import get_random_bytes
from random import randint
import json
from os import rename

class PoorMansKeystore():
    def __init__(self,
                 key = False,
                 fn = USER_DB_FN,
                 autosave = True,
                 ):
        
        if key is False:
            ## Prompt interactively:
            key = getpass.getpass()
            
        self.key = key
        self.fn = fn
        self.accounts = {} ## {username:password}
        self.autosave = autosave
        self._load()
    
    def _load(self):

        print ('LOADING...', self.fn)
        
        self.user_db_password = '1234'#getpass.getpass()

        if not exists("encrypted.bin"):
            self.accounts = {}
        else:
            with open("encrypted.bin", "rb") as ff:
                nonce, tag, ciphertext = [ff.read(x) for x in (16, 16, -1)]

            cipher = AES.new(self.key, AES.MODE_EAX, nonce)
            data = cipher.decrypt_and_verify(ciphertext, tag)

            self.accounts = json.loads(data)

        print ('LOADED', len(self.accounts))
    
    def _save(self):
        
        print ('SAVING...', self.fn)
        
        data = json.dumps(self.accounts)
        
        cipher = AES.new(key, AES.MODE_EAX)
        
        ciphertext, tag = cipher.encrypt_and_digest(data)

        fn_temp = self.fn + '_temp_' + str(randint(1,10000000000))
        
        with open(fn_temp, "wb") as ff:
            for d in (cipher.nonce, tag, ciphertext):
                ff.write(d)
        
        rename(fn_temp, self.fn)
        
        print ('SAVED')
    
    def get_password(self, username, default = False):
        return self.accounts.get(username, False)
    
    def set_password(self, username, password):
        self.accounts[username] = password
        
        if self.autosave:
            self._save()



######## Ethereum parts:

from ethjsonrpc import EthJsonRpc
import json

# main_contract_code = \
# """
# pragma solidity ^0.4.6;

# contract CCCoin {
#     /* Used for vote logging of votes, tok lockup, etc. */
#     event LogMain(bytes);
#     function addLog(bytes val) { 
#         LogMain(val);
#     }
# }
# """

"""
Contract below implements StandardToken (https://github.com/ethereum/EIPs/issues/20) interface, in addition to:
 - Log event = vote, submit items, request tok -> lock.
 - Create user account.
 - Get user balances (tok / lock).
 - Withdraw tok.
 - Change user account owner address.
 - Change contract owner address.
 - Minting / rewards distribution (runnable only by MC, may be called multiple times per rewards cycle due to gas limits)
"""

main_contract_code = \
"""
pragma solidity ^0.4.0;

contract owned { 
    address owner;

    modifier onlyOwner {
        if (msg.sender != owner) throw;
        _;
    }
    function owned() { 
        owner = msg.sender; 
    }
}

contract mortal is owned {
    function kill() {
        if (msg.sender == owner) selfdestruct(owner);
    }
}

contract TokFactory is owned, mortal{ 

     event LogMain(bytes); 

     function addLog(bytes val) {
         LogMain(val);
     }

    mapping(address => address[]) public created;
    mapping(address => bool) public isToken; //verify without having to do a bytecode check.
    bytes public tokByteCode;
    address public verifiedToken;
    event tokenCreated(uint256 amount, address tokenAddress, address owner);
    Tok tok;

    function () { 
      throw; 
    }

    modifier noEther { 
      if (msg.value > 0) { throw; }
      _; 
    }

    modifier needTok { 
      if (address(tok) == 0x0) { throw; }
      _;
    }

    function TokFactory() {
      //upon creation of the factory, deploy a Token (parameters are meaningless) and store the bytecode provably.
      owner = msg.sender;
    }

    function getOwner() constant returns (address) { 
      return owner; 
    }

    function getTokenAddress() constant returns (address) { 
      // if (verifiedToken == 0x0) { throw; }
      return verifiedToken;
    } 

    //verifies if a contract that has been deployed is a validToken.
    //NOTE: This is a very expensive function, and should only be used in an eth_call. ~800k gas
    function verifyToken(address _tokenContract) returns (bool) {
      bytes memory fetchedTokenByteCode = codeAt(_tokenContract);

      if (fetchedTokenByteCode.length != tokByteCode.length) {
        return false; //clear mismatch
      }
      //starting iterating through it if lengths match
      for (uint i = 0; i < fetchedTokenByteCode.length; i ++) {
        if (fetchedTokenByteCode[i] != tokByteCode[i]) {
          return false;
        }
      }

      return true;
    }

    //for now, keeping this internal. Ideally there should also be a live version of this that any contract can use, lib-style.
    //retrieves the bytecode at a specific address.
    function codeAt(address _addr) internal returns (bytes o_code) {
      assembly {
          // retrieve the size of the code, this needs assembly
          let size := extcodesize(_addr)
          // allocate output byte array - this could also be done without assembly
          // by using o_code = new bytes(size)
          o_code := mload(0x40)
          // new "memory end" including padding
          mstore(0x40, add(o_code, and(add(add(size, 0x20), 0x1f), not(0x1f))))
          // store length in memory
          mstore(o_code, size)
          // actually retrieve the code, this needs assembly
          extcodecopy(_addr, add(o_code, 0x20), 0, size)
      }
    }

    function createTok(uint256 _initialAmount, string _name, uint8 _decimals, string _symbol) onlyOwner  returns (address) {
        tok = new Tok(_initialAmount, _name, _decimals, _symbol);
        created[msg.sender].push(address(tok));
        isToken[address(tok)] = true;
        // tok.transfer(owner, _initialAmount); //the creator will own the created tokens. You must transfer them.
        verifiedToken = address(tok); 
        tokByteCode = codeAt(verifiedToken);
        tokenCreated(_initialAmount, verifiedToken, msg.sender);
        return address(tok);
    }
    function rewardToken(address _buyer, uint256 _amount)  onlyOwner returns (bool) {
      return tok.transfer(_buyer, _amount); 
  }
}

contract StandardToken is owned, mortal{

    event Transfer(address sender, address to, uint256 amount);
    event Approval(address sender, address spender, uint256 value);

    /*
     *  Data structures
     */
    struct User {
      bool initialized; 
      address userAddress; 
      bytes32 userName;
      uint256 registerDate;
      uint8 blockVoteCount;    // number of votes this block
      uint256 currentBlock; 
      uint8 totalVotes; 
      mapping (uint8 => Post) votedContent;  // mapping of each vote to post 
    }

    struct Lock {
      uint256 amount; 
      uint256 unlockDate;
    }

    struct Post {
      bool initialized; 
      address creator; 
      bytes32 title;
      bytes32 content; 
      uint256 creationDate; 
      uint8 voteCount;     // total + or - 
      address[] voters;
      mapping (address => uint8) voteResult;     // -1 = downvote , 0 = no vote,  1 = upvote 
    }


    mapping (address => uint256) public balances;
    mapping (address => mapping (address => uint256)) allowed;
    uint256 public totalSupply;
    mapping (address => Lock[]) public lockedTokens;
    mapping (address => Post[]) public posts;
    uint8 public numUsers;
    mapping (address => User) public users;
    address[] userAddress; 

    
    /*
     *  Read and write storage functions
     */
    /// @dev Transfers sender's tokens to a given address. Returns success.
    /// @param _to Address of token receiver.
    /// @param _value Number of tokens to transfer.
    function transfer(address _to, uint256 _value) returns (bool success) {
        if (balances[msg.sender] >= _value && _value > 0) {
            balances[msg.sender] -= _value;
            balances[_to] += _value;
            Transfer(msg.sender, _to, _value);
            return true;
        }
        else {
            return false;
        }
    }

    /// @dev Allows allowed third party to transfer tokens from one address to another. Returns success.
    /// @param _from Address from where tokens are withdrawn.
    /// @param _to Address to where tokens are sent.
    /// @param _value Number of tokens to transfer.
    function transferFrom(address _from, address _to, uint256 _value) returns (bool success) {
        if (balances[_from] >= _value && allowed[_from][msg.sender] >= _value && _value > 0) {
            balances[_to] += _value;
            balances[_from] -= _value;
            allowed[_from][msg.sender] -= _value;
            Transfer(_from, _to, _value);
            return true;
        }
        else {
            return false;
        }
    }

    /// @dev Returns number of tokens owned by given address.
    /// @param _owner Address of token owner.
    function balanceOf(address _owner) constant returns (uint256 balance) {
        return balances[_owner];
    }

    /// @dev Sets approved amount of tokens for spender. Returns success.
    /// @param _spender Address of allowed account.
    /// @param _value Number of approved tokens.
    function approve(address _spender, uint256 _value) returns (bool success) {
        allowed[msg.sender][_spender] = _value;
        Approval(msg.sender, _spender, _value);
        return true;
    }

    /*
     * Read storage functions
     */
    /// @dev Returns number of allowed tokens for given address.
    /// @param _owner Address of token owner.
    /// @param _spender Address of token spender.
    function allowance(address _owner, address _spender) constant returns (uint256 remaining) {
      return allowed[_owner][_spender];
    }

}

contract Tok is StandardToken{ 

    address tokFactory; 

    string name; 
    uint8 decimals;
    string symbol; 

    modifier noEther { 
      if (msg.value > 0) { throw; }
      _; 
    }

    modifier controlled { 
        if (msg.sender != tokFactory) throw; 
        _;
    }
    
    function () {
        //if ether is sent to this address, send it back.
        throw;
    }
    
    function Tok(
        uint256 _initialAmount,
        string _tokenName,
        uint8 _decimalUnits,
        string _tokenSymbol
        ) noEther{
        tokFactory = msg.sender;
        balances[msg.sender] = _initialAmount;               // Give the TokFactory all initial tokens
        totalSupply = _initialAmount;                        // Update total supply
        name = _tokenName;                                   // Set the name for display purposes
        decimals = _decimalUnits;                            // Amount of decimals for display purposes
        symbol = _tokenSymbol;                               // Set the symbol for display purposes
    }

    function getUserAddress(address _user) noEther returns (address) { 
      return users[_user].userAddress; 
    }
    function getUserName(address _user) noEther returns (bytes32) { 
      return users[_user].userName; 
    }

    function register(bytes32 _username) noEther returns (bool success) { 
      User newUser = users[msg.sender];
      newUser.userName = _username;
      newUser.userAddress = msg.sender;
      newUser.registerDate = block.timestamp;
      return true; 

    }

    function mintToken(address _target, uint256 _mintedAmount) controlled {
        balances[_target] += _mintedAmount;
        totalSupply += _mintedAmount;
        Transfer(owner, _target, _mintedAmount);
    }

    function  post(bytes32 _title, bytes32 _content) noEther{
      Post[] posts = posts[msg.sender];
      posts.push(Post({creator: msg.sender, title: _title, content: _content, creationDate: block.timestamp, voteCount: 0}));
    }

    function vote(uint8 _postID, address _creator) noEther {
           User voter = users[msg.sender];
           Post postVotedOn = posts[_creator][_postID];
           if (voter.currentBlock == block.number) {
             // uint256 requiredLock =  (1 * numVotes) ** 3) + 100);  
             // uint256 lockBalance = lockBalance(msg.sender);
             // if (lockBalance < requiredLock) { throw;     }  
           }
           else { 
            voter.blockVoteCount = 0; 
            voter.currentBlock = block.number;
            uint256 totalLock = lockBalance(msg.sender);
            if (totalLock > 100) { 

            } 
           }
    }

    function lockBalance(address lockAccount)  constant returns (uint256) { 
      Lock[] lockedList = lockedTokens[lockAccount];
      uint256 total = 0;  
      for (uint8 i = 0; i < lockedList.length; i++) { 
        total += lockedList[i].amount; 
        }
      return total;
    }
    function calculateLockPayout(uint256 _amount) internal constant controlled { 
      for (uint8 i = 0; i < numUsers; i++) { 
         address temp = userAddress[i]; 
         User user = users[temp]; 
         uint256 userLockBalance = lockBalance(temp);

      }
    }
}
"""

class ContractWrapper:
    
    def __init__(self,
                 events_callback,
                 rpc_host = '127.0.0.1',
                 rpc_port = 9999, ## 8545,
                 confirm_states = {'PENDING':0,
                                   'CONFIRM_1':1,
                                   'CONFIRMED':15,
                                   'STALE':100,
                                   },
                 final_confirm_state = 'CONFIRMED',
                 contract_address = False,
                 ):
        """
        Simple contract wrapper, assists with deploying contract, sending transactions, and tracking event logs.
        
        Args:
          - `events_callback` will be called upon each state transition, according to `confirm_states`, 
             until `final_confirm_state`.
          - `contract_address` contract address, from previous `deploy()` call.
        """

        self.loop_block_num = -1
        
        self.confirm_states = confirm_states
        self.events_callback = events_callback
        
        if contract_address is False:
            if exists(CONTRACT_ADDRESS_FN):
                print ('Reading contract address from file...', CONTRACT_ADDRESS_FN)
                with open(CONTRACT_ADDRESS_FN) as f:
                    d = f.read()
                print ('GOT', d)
                self.contract_address = d
        else:
            self.contract_address = contract_address
        
        self.c = EthJsonRpc(rpc_host, rpc_port)
        
        self.pending_transactions = {}  ## {tx:callback}
        self.pending_logs = {}
        self.latest_block_number = -1

        ###
        
        self.latest_block_num_done = 0
        
    def deploy(self):
        print ('DEPLOYING_CONTRACT...')        
        # get contract address
        xx = self.c.eth_compileSolidity(main_contract_code)
        #print ('GOT',xx)
        compiled = xx['code']
        contract_tx = self.c.create_contract(self.c.eth_coinbase(), compiled, gas=3000000)
        self.contract_address = self.c.get_contract_address(contract_tx)
        print ('DEPLOYED', self.contract_address)
        #self.init_logs_filter()

    def loop_once(self):
        
        if self.c.eth_syncing():
            print ('BLOCKCHAIN_STILL_SYNCING')
            return
        
        if events_callback is not False:
            self.poll_incoming()
        
        self.poll_outgoing()
        

    def poll_incoming(self):
        """
        https://github.com/ethereum/wiki/wiki/JSON-RPC#eth_newfilter
        """
        
        self.latest_block_num = int(self.c.eth_blockNumber(), 16)

        for do_state in ['CONFIRMED',
                         'PENDING',
                         ]:
            
            self.latest_block_num_confirmed = max(0, self.latest_block_num - self.confirm_states[do_state])
            
            from_block = self.latest_block_num_done
            
            to_block = self.latest_block_num_confirmed
            
            got_block = 0
            
            params = {'fromBlock': from_block,
                      'toBlock': to_block,
                      'address': self.contract_address,
                      }
            
            print ('eth_newFilter', 'do_state:', do_state, 'latest_block_num:', self.latest_block_num, 'params:', params)
            
            self.filter = str(self.c.eth_newFilter(params))
            
            print ('eth_getFilterChanges', self.filter)
            
            msgs = self.c.eth_getFilterChanges(self.filter)
            
            print ('GOT', len(msgs))
            
            for msg in msgs:
                
                got_block = int(receipt['blockNumber'], 16)

                self.events_callback((msg, 'todo', do_state))

                self.latest_block_num_done = max(0, max(self.latest_block_num_done, got_block - 1))
        
            
    def send_transaction(self, foo, args, callback = False, send_from = False, block = False):
        """
        1) Attempt to send transaction.
        2) Get first confirmation via transaction receipt.
        3) Re-check receipt again after N blocks pass.
        
        https://github.com/ethereum/wiki/wiki/JSON-RPC#eth_sendtransaction
        """
        
        self.latest_block_num = int(self.c.eth_blockNumber(), 16)
        
        if send_from is False:
            send_from = self.c.eth_coinbase()
        
        send_to = self.contract_address 
        
        tx = self.c.call_with_transaction(send_from, send_to, foo, args)
        
        if block:
            receipt = self.c.eth_getTransactionReceipt(tx) ## blocks to ensure transaction is mined
            #if receipt['blockNumber']:
            #    self.latest_block_number = max(int(receipt['blockNumber'],16), self.latest_block_number)
        else:
            self.pending_transactions[tx] = (callback, self.latest_block_num)
        
        return tx

    def poll_outgoing(self):
        """
        Confirm outgoing transactions.
        """
        for tx, (callback, attempt_block_num) in self.pending_transactions.items():

            ## Compare against the block_number where it attempted to be included:
            
            if (attempt_block_num <= self.latest_block_num - self.confirm_states['CONFIRMED']):
                continue
            
            receipt = self.c.eth_getTransactionReceipt(tx)
            
            if receipt['blockNumber']:
                actual_block_number = int(receipt['blockNumber'],16)
            else:
                ## TODO: wasn't confirmed after a long time.
                actual_block_number = False
            
            ## Now compare against the block_number where it was actually included:
            
            if (actual_block_number is not False) and (actual_block_number >= self.latest_block_num - self.confirm_states['CONFIRMED']):
                callback(receipt)
                del self.pending_transactions[tx]
    
    def read_transaction(self, foo, value):
        rr = self.c.call(self.c.eth_coinbase(), self.contract_address, foo, value)
        return rr

    
    def sign(self, user_address, value):
        rr = self.c.eth_sign(self.c.eth_coinbase(), self.contract_address, user_address, value)
        return rr
        


def deploy_contract(via_cli = False):
    """
    Deploy new instance of this dApp to the blockchain.
    """
    
    fn = CONTRACT_ADDRESS_FN
    
    assert not exists(fn), ('Delete this file first:', fn)
    
    if not exists(DATA_DIR):
        mkdir(DATA_DIR)
    
    cont = ContractWrapper()
    
    addr = cont.deploy()
    
    with open(fn) as f:
        f.write(addr)
    
    print ('DONE', addr, '->', fn)

############### Utils:

from os import urandom
    
def dumps_compact(h):
    print ('dumps_compact',h)
    return json.dumps(h, separators=(',', ':'), sort_keys=True)

def loads_compact(d):
    print ('loads_compact',d)
    r = json.loads(d)#, separators=(',', ':'))
    return r


from Crypto.Hash import keccak

sha3_256 = lambda x: keccak.new(digest_bits=256, data=x).digest()

def web3_sha3(seed):
    return '0x' + (sha3_256(str(seed)).encode('hex'))

#assert web3_sha3('').encode('hex') == 'c5d2460186f7233c927e7db2dcc703c0e500b653ca82273b7bfad8045d85a470'
assert web3_sha3('') == '0xc5d2460186f7233c927e7db2dcc703c0e500b653ca82273b7bfad8045d85a470'

def consistent_hash(h):
    ## Not using `dumps_compact()`, in case we want to change that later.
    return web3_sha3(json.dumps(h, separators=(',', ':'), sort_keys=True))

import multiprocessing

class SharedCounter(object):
    def __init__(self, n=0):
        self.count = multiprocessing.Value('i', n)

    def increment(self, n=1):
        """ Increment the counter by n (default = 1) """
        with self.count.get_lock():
            self.count.value += n
            r = self.count.value
        return r

    def decrement(self, n=1):
        """ Decrement the counter by n (default = 1) """
        with self.count.get_lock():
            self.count.value -= n
            r = self.count.value
        return r

    @property
    def value(self):
        """ Return the value of the counter """
        return self.count.value


############## Shared among all forked sub-processes:

RUN_ID = get_random_bytes(32).encode('hex')

TRACKING_NUM = SharedCounter()

manager = multiprocessing.Manager()

LATEST_NONCE = manager.dict() ## {api_key:nonce}

USER_VOTES = manager.dict() ## {public_key:set()}          ## Received via blockchain.
USER_PENDING_VOTES = manager.dict() ## {public_key:set()}  ## Received via HTTP.

USER_FLAGS = manager.dict() ## {public_key:set()}          ## Received via blockchain.
USER_PENDING_FLAGS = manager.dict() ## {public_key:set()}  ## Received via HTTP.

USER_DB = manager.dict() ## {'public_key':user_info}

CHALLENGES_DB = manager.dict() ## {'public_key':challenge}

SEEN_USERS_DB = manager.dict() ## {'public_key':1}


TEST_MODE = True

the_db = {'USER_VOTES':USER_VOTES,
          'USER_PENDING_VOTES':USER_PENDING_VOTES,
          'USER_FLAGS':USER_FLAGS,
          'USER_PENDING_FLAGS':USER_PENDING_FLAGS,
          }

############### Load keypair key store:

keystore_users_fn = 'keystore_users.json'

if exists(keystore_users_fn):
    with open(keystore_users_fn) as f:
        d = f.read()
    h = json.loads(d)
    USER_DB.update(h)

    print ('LOADED', len(h), keystore_users_fn)

############### CCCoin Core API:

from ethjsonrpc.utils import hex_to_dec, clean_hex, validate_block

from random import choice


def generate_keypair():
    from ethereum import transactions
    from ethereum import utils

    priv = urandom(32)
    pub = utils.privtoaddr(priv)
    
    return utils.decode_addr(pub), priv
    
    

class CCCoinAPI:
    def _validate_api_call(self):
        pass
    
    def __init__(self, mode = 'web'):
        
        assert mode in ['web', 'witness', 'audit']
        
        self.mode = mode
        
        ## TOK rewards settings:
        
        self.REWARDS_CURATION = 90.0   ## Voting rewards
        self.REWARDS_POSTING = 10.0    ## Posting rewards
        self.REWARDS_WITNESS = 10.0    ## Witness rewards
        self.REWARDS_SPONSOR = 10.0    ## Web nodes that cover basic GAS / TOK for users on their node.
        
        self.REWARDS_FREQUENCY = 140   ## 140 blocks = 7 hours
        
        self.MAX_UNBLIND_DELAY = 20    ## Maximum number of blocks allowed between submitting a blind vote and unblinding.
        
        self.MAX_GAS_DEFAULT = 10000       ## Default max gas fee per contract call.
        self.MAX_GAS_REWARDS = 10000       ## Max gas for rewards function.
        
        self.NEW_USER_TOK_DONATION = 1  ## Free LOCK given to new users that signup through this node.
        
        ## Balances:

        self.balances_tok = {}
        
        ## Contract interface:
        
        self.cw = ContractWrapper(events_callback = self.rewards_and_auditing_callback)

        ## Key store for users on this node:
        
        self.master_password = 'todo'#getpass.getpass()

        self.the_keystore = PoorMansKeystore(key = self.master_password) ## TODO - allow multiple keystore files?

        ## Check that accounts that are both in the local keystore & the geth keystore:
        
        self.working_accounts = {} 
        
        num_good = 0
        num_bad = 0

        if not TEST_MODE:
            accounts = self.cw.c._call('personal_listAccounts')

            for addr in accounts:
                upw = self.the_keystore.get_password(addr)

                r = self.cw.c._call('personal_unlockAccount', [addr, upw, 0])

                if (upw is not False) and r:
                    self.working_accounts[addr] = upw
                    num_good += 1
                else:
                    num_bad += 1

            print ('unlocked:', num_good, 'failed:', num_bad)
            #print ('Press Enter...')
            #raw_input()
        
        ## Tracking:
        
        self.latest_block_number = -1
        self.is_caught_up = False
        
        ## User tracking:

        self.user_info = {}
        self.user_tok_balances = {}
        self.user_lok_balances = {}
        
        ## Caches:
        
        self.items_cache = {}     ## {item_id:item}
        self.recent_voting_hist = []  ## {hour:{item_id:num_votes}}
        
        self.cur_unblind_block_num = -1
        
        ## Items and Votes DB, split into pending and confirmed (>= confirm_wait_blocks).
        ## TODO Pending are ignored if not confirmed within a certain amount of time.
        
        self.items_pending = {}
        self.items_confirmed = {}
        self.votes_pending = {}
        self.votes_confirmed = {}
        
        ## Stores votes until rewards are paid:
        
        self.my_blind_votes =  {}          ## {vote_hash: vote_string}
        self.my_votes_unblinded = {}       ## {vote_hash: block_number}

        ##

        self.poster_ids = {}               ## {item_id:poster_id}
        
        self.new_rewards = {}              ## {voter_id:tok}

        self.total_lock_at_block = {}      ## {block_num:tok}
        self.unblinded_votes_at_block = {} ## {block_num:{sig:(voter_id, item_id, voter_lock)}}

        self.old_voters_for_item = {}      ## {item_id:set(voters)}
        self.new_voters_for_item = {}      ## {item_id:set(voters)}

        self.sponsors = {}
        
    def rewards_and_auditing_callback(self,
                                      msg,
                                      receipt,
                                      confirm_level,
                                      ):
        """
        """
        
        ## Proceed to next step for recently committed transactions:
        
        try:
            hh = loads_compact(msg['data'].decode('hex'))
        except:
            print ('BAD_MESSAGE', msg)
            return
        
        if confirm_level == 'CONFIRMED':

            block_number = int(msg['blockNumber'], 16)
            
            ## REWARDS:
            
            if is_caught_up and (block_number > self.latest_block_number):

                ## GOT NEW BLOCK:

                self.latest_block_number = max(block_number, self.latest_block_number)
                
                ## Mint TOK rewards for the old block, upon each block update:
                
                doing_block_id = block_number - (self.MAX_UNBLIND_DELAY + 1)
                
                total_lock_this_round = self.total_lock_at_block.get(doing_block_id, 0.0)
                
                for sig, (voter_id, item_id, voter_lock) in self.unblinded_votes_at_block.get(doing_block_id, {}).iteritems():

                    item_poster_id = self.poster_ids[item_id]
                    
                    if item_id not in self.new_voters_for_item:
                        self.new_voters_for_item[item_id] = set()
                    self.new_voters_for_item[item_id].add(voter_id)
                    
                    reward_per_voter = self.REWARDS_CURATION * (voter_lock / total_lock_this_item) * (total_lock_this_item / total_lock_this_round) / len(self.old_voters_for_item[item_id])
                    
                    reward_poster = self.REWARDS_POSTING * (total_lock_this_item / total_lock_this_round)
                    
                    for old_voter_id in self.old_voters_for_item[item_id]:

                        ## Curator rewards:
                        self.new_rewards[old_voter_id] = self.new_rewards.get(old_voter_id, 0.0) + reward_per_voter

                        ## Sponsor rewards for curation:
                        if old_voter_id in self.sponsors:
                            self.new_rewards[self.sponsors[old_voter_id]] = self.new_rewards.get(self.sponsors[old_voter_id], 0.0) +  (self.REWARDS_SPONSOR / self.REWARDS_CURATION)
                        
                    self.new_rewards[item_poster_id] = self.new_rewards.get(item_poster_id, 0.0) + reward_poster
                
                ## Occasionally distribute rewards:

                if (block_number % self.REWARDS_FREQUENCY) == 0:

                    assert confirm_level == 'CONFIRMED', confirm_level
                    
                    if self.mode == 'audit':

                        ## TODO - Wait a little longer, then check that previous batch paid out correctly.
                        
                        pass
                    
                    elif self.mode == 'witness':
                        
                        rr = dumps_compact({'t':'mint', 'rewards':self.new_rewards})

                        tx = self.cw.send_transaction('addLog(bytes)',
                                                      [rr],
                                                      value = self.MAX_GAS_DEFAULT,
                                                      )

                        xx = self.new_rewards.items()

                        tx = self.cw.send_transaction('mintTok(bytes)',
                                                      [[x for x,y in xx],
                                                       [y for x,y in xx],
                                                      ],
                                                      value = self.MAX_GAS_REWARDS,
                                                      )
                        self.new_rewards.clear()
                
                ## Cleanup:
                
                if doing_block_id in self.unblinded_votes_at_block:
                    del self.unblinded_votes_at_block[doing_block_id]

                for item_id,voters in self.new_voters_for_item.iteritems():
                    
                    if item_id not in self.old_voters_for_item:
                        self.old_voters_for_item[item_id] = set()
                    
                    self.old_voters_for_item[item_id].update(voters)
                    
                self.new_voters_for_item.clear()
                
            ## HANDLE LOG EVENTS:
            
            if hh['t'] == 'vote_blind':
                ## Got blinded vote, possibly from another node, or previous instance of self:
                
                if hh['sig'] in self.my_votes:
                    ## blind vote submitted from my node:
                    self.votes_confirmed[hh['sig']] = msg['blockNumber']
                    del self.votes_pending_confirm[hh['sig']]
                    
                else:
                    ## blind vote submitted from another node:
                    pass

                self.votes_blind_block[hh['sig']] = (hh['user_id'], msg['blockNumber']) ## latest vote
            
            elif hh['t'] == 'vote_unblind':
                ## Got unblinded vote, possibly from another node, or previous instance of self:
                
                old_user_id, old_block_number = self.votes_blind_block[hh['sig']]
                
                sig_expected = hmac.new(str(hh['secret']), str(post_data), hashlib.sha512).hexdigest()
                
                #assert hh['user_id'] == old_user_id
                
                ## ignore outdated votes:
                
                if hh['sig'] == old_sig:
                    
                    votes = loads_compact(hh['orig'])

                    orig_block_num = self.lookup_orig_blocknum

                    if orig_block_num > self.cur_unblind_block_num:
                        ## clear out previous
                        self.recent_voting_hist[time_bucket] = {}
                        self.cur_unblind_block_num = orig_block_num
                    
                    time_bucket = orig_block_num % 100 ## 
                    
                    if time_bucket not in self.recent_voting_hist:
                        self.recent_voting_hist[time_bucket] = {}
                    
                    for vote in votes:
                        assert vote['dir'] in [1], vote['dir'] ## only positive votes for v1
                        
                        self.total_lock_at_block[block_num] += self.user_lok_balances[hh['user_id']]

                        if block_num not in self.unblinded_votes_at_block:
                            self.unblinded_votes_at_block[block_num] = {}
                        
                        if hh['sig'] not in self.unblinded_votes_at_block[block_num]:
                            self.unblinded_votes_at_block[block_num][hh['sig']] = []
                        
                        self.unblinded_votes_at_block[block_num][hh['sig']].append((hh['user_id'],
                                                                                    vote['item_id'],
                                                                                    self.user_lok_balances[hh['user_id']],
                                                                                    ))
                        
                        self.recent_voting_hist[time_bucket][vote['item_id']] += 1 #vote['dir']
            
            elif hh['t'] == 'update_user':

                ## For now, updates sponsor:
                
                if ('user_info' in hh) and ('sponsor' in hh['user_info']):
                    self.sponsors[msg['address']] = hh['user_info']['sponsor']
            
            elif hh['t'] == 'post':
                
                post = loads_compact(hh['orig']) ## {'t':'post', 'title': title, 'url':'url', 'user_id':user_id}
                
                item_id = web3_sha3(hh['orig'])
                
                post['item_id'] = item_id

                self.items_cache[post['item_id']] = post
                
                self.poster_ids[item_id] = post
            
            elif hh['t'] == 'lock_tok':
                ## request to lockup tok

                self.balances_tok
            
            for sig, block_number in self.my_votes_confirmed.iteritems():
                pass
        
    def deploy_contract(self,):
        """
        Create new instance of dApp on blockchain.
        """
        self.cw.deploy()
    

    def create_account(self,
                       user_info,
                       password,
                       public_wallet_address = False,
                       ):
        """
        Note: 
        User needs LOCK balance before he can perform any accounts. 

        Custom anti-spam measures should be added here by nodes, to prevent draining of funds.

        New keypair is generated if no public wallet address is passed in.
        """
        

        user_info['sponsor'] = self.cw.c.eth_coinbase()
        
        private_wallet_key = False
        
        if not public_wallet_address:
            public_wallet_address, private_wallet_key = generate_keypair()
        
        if not TEST_MODE:
            ## TODO: temporary

            assert user_info['username']

            if user_info['username'] in self.username_to_id:
                return {'success':False, 'error':'USERNAME_TAKEN'}

            user_address = self.cw.c._call('personal_newAccount', [self.cw.c.eth_coinbase(), passphrase])

            self.the_keystore.set_password(user_address, passphrase)
            self.working_accounts[addr] = passphrase

            rr = dumps_compact({'t':'update_user',
                                'user_info':user_info,
                                'public_wallet_address':public_wallet_address,
                                })

            ## Sent from contract owner, who will fund initial TOK and gas fees:

            tx = self.cw.send_transaction('addLog(bytes)',
                                          [rr,
                                           self.NEW_USER_TOK_DONATION,
                                           ],
                                          send_from = user_id, ## Required, since sponsor can be controlled.
                                          value = self.MAX_GAS_DEFAULT,
                                          )

            self.username_to_id[user_info['username']] = user_address ## TODO, wait for confirmations?
            
        else:
            uu = choice(USER_DB.values())
            user_address = uu['public_key']

        
        
        return {'success':True,
                'user_info':uu,
                'user_id':public_wallet_address,
                'public_wallet_address':public_wallet_address,
                'private_wallet_key':private_wallet_key,
                #'tx':tx,
                }

    
    def post_item(self,
                  user_id,
                  item_data_string,
                  sig,
                  callback = False
                  ):
        print ('INSIDE post_item')
        
        hh = {'t':'post', 'user_id':user_id, 'sig':'sig', 'item_data':item_data_string}
        
        item_id = consistent_hash(hh)
        
        print ('INSIDE post_item2', item_id)
        
        rr = dumps_compact(hh)
        
        print ('INSIDE post_item3')
        
        item_data = loads_compact(item_data_string)

        print ('INSIDE post_item4')
        
        if item_id in self.items_cache:
            print 'RETURN1'
            return {'success':True, 'item_id':item_id}


        print ('INSIDE post_item5')

        if not TEST_MODE:
            if user_id not in self.working_accounts:
                print 'RETURN2'
                return {'success':False, 'error':'ACCOUNT_NOT_LOADED'}
        
        hh['created'] = int(time())
        hh['item_id'] = item_id
        hh['score'] = 1
        hh['score_weighted'] = 1
        
        ## TODO: put LOCK-weighted scores in cache?
        
        self.items_cache[item_id] = hh

        if not TEST_MODE:
            tx = self.cw.send_transaction('addLog(bytes)',
                                          [rr],
                                          send_from = user_id,
                                          value = self.MAX_GAS_DEFAULT,
                                          callback = callback,
                                          )
        print 'RETURN3'
        return {'success':True, 'item_id':item_id}
    
    def submit_blind_action(self,
                            vote_data,
                            ):
        """
        Submit blinded vote(s) to blockchain.
        
        `vote_data` is signed message containing blinded vote(s), of the form:
        
        {   
            "payload": "{\"command\":\"vote_blind\",\"blind_hash\":\"03689918bda30d10475d2749841a22b30ad8d8d163ff2459aa64ed3ba31eea7c\",\"num_items\":1,\"nonce\":1485769087047}",
            "sig": {
                "sig_s": "4f529f3c8fabd7ecf881953ee01cfec5a67f6b718364a1dc82c1ec06a2c65f14",
                "sig_r": "dc49a14c82f7d05719fa893efbef28b337b913f2be0b1675f3f3722276338730",
                "sig_v": 28
            },
            "pub": "11f1b3f728713521067451ae71e795d05da0298ac923666fb60f6d0f152725b0535d2bb8c5ae5fefea8a6db5de2ac800b658f53f3afa0113f6b2e34d25e0f300"
        }
        """
        
        print ('START_SUBMIT_BLIND_ACTION')
        
        tracking_id = RUN_ID + '|' + str(TRACKING_NUM.increment())

        ## Sanity checks:
        
        assert vote_data['sig']
        assert vote_data['pub']
        json.loads(vote_data['payload'])
        
        rr = dumps_compact(vote_data)
        
        if not TEST_MODE:
            tx = self.cw.send_transaction('addLog(bytes)',
                                          [rr],
                                          #send_from = user_id,
                                          value = self.MAX_GAS_DEFAULT,
                                          callback = False,
                                          )

        print ('DONE_SUBMIT_BLIND_ACTION')
        
        return {'success':True,
                'tracking_id':tracking_id,
                "command":"blind_votes",
                }
    
    def submit_unblind_action(self,
                              vote_data,
                              ):
        """
        Submit unblinded votes to the blockchain.

        `vote_data` is signed message revealing previously blinded vote(s), of the form:
        
        {   
            "payload": "{\"command\":\"vote_unblind\",\"blind_hash\":\"03689918bda30d10475d2749841a22b30ad8d8d163ff2459aa64ed3ba31eea7c\",\"blind_reveal\":\"{\\\"votes\\\":[{\\\"item_id\\\":\\\"99\\\",\\\"direction\\\":1}],\\\"rand\\\":\\\"CnKDXhTSU2bdqX4Y\\\"}\",\"nonce\":1485769087216}",
            "sig": {
                "sig_s": "56a5f496962e9a6dedd8fa0d4132c3ffb627cf0c8239c625f857a22d5ee5e080",
                "sig_r": "a846493114e98c0e8aa6f398d33bcbca6e1c277ac9297604ddecb397dc7ed3d8",
                "sig_v": 28
            },
            "pub": "11f1b3f728713521067451ae71e795d05da0298ac923666fb60f6d0f152725b0535d2bb8c5ae5fefea8a6db5de2ac800b658f53f3afa0113f6b2e34d25e0f300"
        }
        """
        
        print ('START_UNBLIND_ACTION')
        
        tracking_id = RUN_ID + '|' + str(TRACKING_NUM.increment())
        
        payload = json.loads(vote_data['payload'])
        
        payload_inner = json.loads(payload['blind_reveal'])
        
        ## Immediately add to local caches:
        
        print ('GOT_INNER', payload_inner)
        
        if payload['item_type'] == 'votes':
            
            for vote in payload_inner['votes']:
                if vote['direction'] in [1,-1]:
                    USER_PENDING_VOTES[(vote_data['pub'], vote['item_id'])] = vote['direction']
                elif vote['direction'] == 0:
                    try:
                        del USER_PENDING_VOTES[(vote_data['pub'], vote['item_id'])]
                    except:
                        pass
                elif vote['direction'] == 2:
                    USER_PENDING_FLAGS[(vote_data['pub'], vote['item_id'])] = vote['direction']
                elif vote['direction'] == -2:
                    try:
                        del USER_PENDING_FLAGS[(vote_data['pub'], vote['item_id'])]
                    except:
                        pass
                else:
                    assert False, vote['direction']
                    
        elif payload['item_type'] == 'posts':
            pass
        
        #print ('CACHED_VOTES', dict(USER_PENDING_VOTES))
            
        rr = dumps_compact(vote_data)
        
        if not TEST_MODE:
            ## Send to blockchain:
            
            tx = self.cw.send_transaction('addLog(bytes)',
                                          [rr],
                                          #send_from = user_id,
                                          value = self.MAX_GAS_DEFAULT,
                                          )
            tracking_id = tx
        
        print ('DONE_UNBLIND_ACTION')
        
        return {'success':True, 'tracking_id':tracking_id, "command":"unblind_action"}
        
    def lockup_tok(self):
        tx = self.cw.send_transaction('lockupTok(bytes)',
                                      [rr],
                                      value = self.MAX_GAS_DEFAULT,
                                      )

    def get_balances(self,
                     user_id,
                     ):
        xx = self.cw.read_transaction('balanceOf(address)',
                                      [rr],
                                      value = self.MAX_GAS_DEFAULT,
                                      )
        rr = loads_compact(xx['data'])
        return rr

    def withdraw_lock(self,):
        tx = self.cw.send_transaction('withdrawTok(bytes)',
                                      [rr],
                                      value = self.MAX_GAS_DEFAULT,
                                      )
        
    def get_items(self,
                  offset = 0,
                  increment = 50,
                  sort_by = 'score',
                  ):
        """
        Get sorted items.
        """
        print ('GET_ITEMS', offset, increment, sort_by)
        
        assert sort_by in ['score', 'created'], sort_by
        
        rr = list(sorted([(x[sort_by],x) for x in self.items_cache.values()], reverse=True))
        rr = rr[offset:offset + increment]
        rr = [y for x,y in rr]
        
        rrr = {'success':True, 'items':rr, 'sort':sort_by}
        
        return rrr
        
    
##
####
##


def trend_detection(input_gen,
                    window_size = 7,
                    prev_window_multiple = 1,
                    empty_val_2 = 1,
                    input_is_absolutes = False, ## otherwise, must convert to differences
                    do_ttl = False,
                    ttl_halflife_steps = 1,
                    ):
    """
    Basic in-memory KL-divergence based trend detection, with some helpers.
    """
    
    from math import log
    from sys import maxint
    
    tot_window_size = window_size + window_size * prev_window_multiple
    
    all_ids = set()
    windows = {}        ## {'product_id':[1,2,3,4]}

    the_prev = {}       ## {item_id:123}
    the_prev_step = {}  ## {item_id:step}
    
    max_score = {}      ## {item_id:score}
    max_score_time = {} ## {item_id:step_num}
    
    first_seen = {}     ## {item_id:step_num}
    
    output = []
    
    for c,hh in enumerate(input_gen):

        output_lst = []
        
        #step_num = hh['step']
        
        ## For seen items:
        for item_id,value in hh['values'].iteritems():
            
            if item_id not in first_seen:
                first_seen[item_id] = c
                        
            all_ids.add(item_id)

            if item_id not in windows:
                windows[item_id] = [0] * tot_window_size

            if item_id not in the_prev:
                the_prev[item_id] = value
                the_prev_step[item_id] = c - 1
                
            if input_is_absolutes:
                
                nn = (value - the_prev[item_id]) / float(c - the_prev_step[item_id])
                
                windows[item_id].append(nn)
                                
            else:
                windows[item_id].append(value)
            
            windows[item_id] = windows[item_id][-tot_window_size:]
            
            the_prev[item_id] = value
            the_prev_step[item_id] = c

        # Fill in for unseen items:
        for item_id in all_ids.difference(hh['values'].keys()):
            windows[item_id].append(0)
            
            windows[item_id] = windows[item_id][-tot_window_size:]

        if c < tot_window_size:
            continue

        
        ## Calculate on windows:
        for item_id,window in windows.iteritems():

            window = [max(empty_val_2,x) for x in window]
            
            cur_win = window[-window_size:]
            prev_win = window[:-window_size]
            
            cur = sum(cur_win) / float(window_size)
            prev = sum(prev_win) / float(window_size * prev_window_multiple)  #todo - seen for first time?
            
            if len([1 for x in prev_win if x > empty_val_2]) < window_size:
                #ignore if too many missing
                score = 0
            else:
                score = prev * log( cur / prev )
            
            prev_score = max_score.get(item_id, -maxint)
            
            if score > prev_score:
                max_score_time[item_id] = c
                
            max_score[item_id] = max(prev_score, score)

            #Sd(h, t) = SM(h) * (0.5)^((t - tmax)/half-life)
            if do_ttl:
                score = max_score[item_id] * (0.5 ** ((c - max_score_time[item_id])/float(ttl_halflife_steps)))

            output_lst.append((score,item_id,window))
            
        output_lst.sort(reverse=True)
        output.append(output_lst)

    return output

def test_trend_detection():
    trend_detection(input_gen = [{'values':{'a':5,'b':2,}},
                                 {'values':{'a':7,'b':2,}},
                                 {'values':{'a':9,'b':2,}},
                                 {'values':{'a':11,'b':4,}},
                                 {'values':{'a':13,'b':5,}},
                                 {'values':{'a':16,'b':6,'c':1,}},
                                 {'values':{'a':17,'b':7,'c':1,'d':1}},
                                 ],
                    window_size = 2,
                    prev_window_multiple = 1,
                    input_is_absolutes = True,
                    do_ttl = True,
                    )

##
#### Generic helper functions for web server:
##

def intget(x,
           default = False,
           ):
    try:
        return int(x)
    except:
        return default

def floatget(x,
             default = False,
             ):
    try:
        return float(x)
    except:
        return default

    
def raw_input_enter():
    print 'PRESS ENTER...'
    raw_input()


def ellipsis_cut(s,
                 n=60,
                 ):
    s=unicode(s)
    if len(s)>n+1:
        return s[:n].rstrip()+u"..."
    else:
        return s


def shell_source(fn_glob,
                 allow_unset = False,
                 ):
    """
    Source bash variables from file. Input filename can use globbing patterns.
    
    Returns changed vars.
    """
    import os
    from os.path import expanduser
    from glob import glob
    from subprocess import check_output
    from pipes import quote
    
    orig = set(os.environ.items())
    
    for fn in glob(fn_glob):
        
        fn = expanduser(fn)
        
        print ('SOURCING',fn)
        
        rr = check_output("source %s; env -0" % quote(fn),
                          shell = True,
                          executable = "/bin/bash",
                          )
        
        env = dict(line.split('=',1) for line in rr.split('\0'))
        
        changed = [x for x in env.items() if x not in orig]
        
        print ('CHANGED',fn,changed)

        if allow_unset:
            os.environ.clear()
        
        os.environ.update(env)
        print env
    
    all_changed = [x for x in os.environ.items() if x not in orig]
    return all_changed
    

def terminal_size():
    """
    Get terminal size.
    """
    h, w, hp, wp = struct.unpack('HHHH',fcntl.ioctl(0,
                                                    termios.TIOCGWINSZ,
                                                    struct.pack('HHHH', 0, 0, 0, 0),
                                                    ))
    return w, h

def space_pad(s,
              n=20,
              center=False,
              ch = '.'
              ):
    if center:
        return space_pad_center(s,n,ch)    
    s = unicode(s)
    #assert len(s) <= n,(n,s)
    return s + (ch * max(0,n-len(s)))

def usage(functions,
          glb,
          entry_point_name = False,
          ):
    """
    Print usage of all passed functions.
    """
    try:
        tw,th = terminal_size()
    except:
        tw,th = 80,40
                   
    print
    
    print 'USAGE:',(entry_point_name or ('python ' + sys.argv[0])) ,'<function_name>'
        
    print
    print 'Available Functions:'
    
    for f in functions:
        ff = glb[f]
        
        dd = (ff.__doc__ or '').strip() or 'NO_DOCSTRING'
        if '\n' in dd:
            dd = dd[:dd.index('\n')].strip()

        ee = space_pad(f,ch='.',n=40)
        print ee,
        print ellipsis_cut(dd, max(0,tw - len(ee) - 5))
    
    sys.exit(1)

    
def set_console_title(title):
    """
    Set console title.
    """
    try:
        title = title.replace("'",' ').replace('"',' ').replace('\\',' ')
        cmd = "printf '\033k%s\033\\'" % title
        system(cmd)
    except:
        pass

import sys
from os import system

def setup_main(functions,
               glb,
               entry_point_name = False,
               ):
    """
    Helper for invoking functions from command-line.
    """
        
    if len(sys.argv) < 2:
        usage(functions,
              glb,
              entry_point_name = entry_point_name,
              )
        return

    f=sys.argv[1]
    
    if f not in functions:
        print 'FUNCTION NOT FOUND:',f
        usage(functions,
              glb,
              entry_point_name = entry_point_name,
              )
        return

    title = (entry_point_name or sys.argv[0]) + ' '+ f
    
    set_console_title(title)
    
    print 'STARTING ',f + '()'

    ff=glb[f]

    ff(via_cli = True) ## New: make it easier for the functions to have dual CLI / API use.


##
### Web frontend:
##


import json
import ujson
import tornado.ioloop
import tornado.web
from time import time
from tornadoes import ESConnection

import tornado
import tornado.options
import tornado.web
import tornado.template
import tornado.gen
import tornado.auth
from tornado.web import RequestHandler
from tornado.httpserver import HTTPServer
from tornado.ioloop import IOLoop
from tornado.options import define, options

############## Authentication:

import hmac
import hashlib
import urllib
import urllib2
import json
from time import time

from urllib import quote
import tornado.web
import tornado.gen

import pipes


def auth_test(rq,
              user_key,
              secret_key,
              api_url = 'http://127.0.0.1:50000/api',
              ):
    """
    HMAC authenticated calls, with nonce.
    """
    rq['nonce'] = int(time()*1000)
    #post_data = urllib.urlencode(rq)
    post_data = dumps_compact(rq)
    sig = hmac.new(secret_key, post_data, hashlib.sha512).hexdigest()
    headers = {'Sig': sig,
               'Key': user_key,
               }
    
    print ("REQUEST:\n\ncurl -S " + api_url + " -d " + pipes.quote(post_data) + ' -H ' + pipes.quote('Sig: ' + headers['Sig']) + ' -H ' + pipes.quote('Key: ' + headers['Key']))

    return

    ret = urllib2.urlopen(urllib2.Request(api_url, post_data, headers))
    hh = json.loads(ret.read())
    return hh


def vote_helper(api_url = 'http://big-indexer-1:50000/api',
                via_cli = False,
                ):
    """
    USAGE: python offchain.py vote_helper user_pub_key user_priv_key vote_secret vote_json
    """
    
    user_key = sys.argv[2]
    secret_key = sys.argv[3]
    vote_secret = sys.argv[4]
    rq = sys.argv[5]
    
    rq = json.loads(rq)
    
    num_votes = len(rq['votes'])
        
    sig1 = hmac.new(vote_secret, dumps_compact(rq), hashlib.sha512).hexdigest()
    
    post_data = dumps_compact({'command':'vote_blind', 'sig':sig1, 'num_votes':num_votes, 'nonce':int(time()*1000)})
    
    sig2 = hmac.new(secret_key, post_data, hashlib.sha512).hexdigest()
    
    print ('REQUEST:')
    print ("curl -S " + api_url + " -d " + pipes.quote(post_data) + ' -H ' + pipes.quote('Sig: ' + sig2) + ' -H ' + pipes.quote('Key: ' + user_key))


def sig_helper(user_key = False,
               secret_key = False,
               rq = False,
               via_cli = False,
               ):
    """
    CLI helper for authenticated requests. Usage: api_call user_key secret_key json_string
    """
    #print sys.argv
    
    if via_cli:
        user_key = sys.argv[2]
        secret_key = sys.argv[3]
        rq = sys.argv[4]
    
    rq = json.loads(rq)
    
    print ('THE_REQUEST', rq)
    
    rr = auth_test(rq,
                   user_key,
                   secret_key,
                   api_url = 'http://127.0.0.1:50000/api',
                   )
    
    print json.dumps(rr, indent = 4)


import functools
import urllib
import urlparse


from uuid import uuid4

from ujson import loads,dumps
from time import time


class AuthState:
    def __init__(self):
        pass
        
    def login_and_init_session(self,
                               caller,
                               session,
                               ):
        print ('login_and_init_session()')
        assert session
        
        session['last_updated'] = time()
        session = dumps(session)
        caller.set_secure_cookie('auth',session)
        
    def logout(self,
               caller,
               ):
        caller.set_secure_cookie('auth','false')
        
    def update_session(self,
                       caller,
                       session,
                       ):
        print ('update_session()')
        assert session
        
        session['last_updated'] = int(time())
        session = dumps(session)
        caller.set_secure_cookie('auth',session)
    

def get_session(self,
                extend = True,
                ):

    ## Track some basic metrics:
    
    referer=self.request.headers.get('Referer','')
    orig_referer=self.get_secure_cookie('orig_referer')
    
    if not orig_referer:
        self.set_secure_cookie('orig_referer',
                               str(referer),
                               )
    
        orig_page=self.get_secure_cookie('orig_page')
        if not orig_page:
            self.set_secure_cookie('orig_page',
                                   str(self.request.uri),
                                   )
        
        orig_time=self.get_secure_cookie('orig_time')
        if not orig_time:
            self.set_secure_cookie('orig_time',
                                   str(time()),
                                   )
        
    ## Check auth:
    
    r = self.get_secure_cookie('auth')#,False
    
    print ('get_session() AUTH',repr(r))
    
    if not r:
        self.set_secure_cookie('auth','false')
        return False
    
    session = loads(r)
    
    if not session:
        self.set_secure_cookie('auth','false')
        return False
    
    return session


def validate_api_call(post_data,
                      user_key,
                      secret_key,
                      sig,
                      ):
    """
    Shared-secret. HMAC authenticated calls, with nonce.
    """

    sig_expected = hmac.new(str(secret_key), str(post_data), hashlib.sha512).hexdigest()
    
    if sig != sig_expected:
        print ('BAD SIGNATURE', 'user_key:', user_key)
        return (False, 'BAD_SIGNATURE')
    
    rq = json.loads(post_data)
    
    if (user_key in LATEST_NONCE) and (rq['nonce'] <= LATEST_NONCE[user_key]):
        print ('OUTDATED NONCE')
        return (False, 'OUTDATED NONCE')

    LATEST_NONCE[user_key] = rq['nonce']
    
    return (True, '')


def lookup_session(self,
                   public_key,
                   ):
    return USER_DB.get(public_key, False)


def check_auth_shared_secret(auth = True,
                             ):
    """
    Authentication via HMAC signatures, nonces, and a local keypair DB.
    """
    
    def decorator(func):
        
        def proxyfunc(self, *args, **kw):

            user_key = dict(self.request.headers).get("Key", False)
            
            print ('AUTH_CHECK_USER',user_key)
            
            self._current_user = lookup_session(self, user_key)
            
            print ('AUTH_GOT_USER', self._current_user)

            print ('HEADERS', dict(self.request.headers))
            
            if auth:
                
                if self._current_user is False:
                    self.write_json({'error':'USER_NOT_FOUND', 'message':user_key})
                    #raise tornado.web.HTTPError(403)
                    return

                post_data = self.request.body
                sig = dict(self.request.headers).get("Sig", False)
                secret_key = self._current_user['private_key']

                if not (user_key or sig or secret_key):
                    self.write_json({'error':'AUTH_REQUIRED'})
                    #raise tornado.web.HTTPError(403)
                    return

                r1, r2 = validate_api_call(post_data,
                                           user_key,
                                           secret_key,
                                           sig,
                                           )
                if not r1:

                    self.write_json({'error':'AUTH_FAILED', 'message':r2})
                    #raise tornado.web.HTTPError(403)
                    return
            
            func(self, *args, **kw)

            return
        return proxyfunc
    return decorator


def check_auth_asymmetric(needs_read = False,
                          needs_write = False,
                          cookie_expiration_time = 999999999,
                          ):
    """
    Authentication based on digital signatures or encrypted cookies.
    
    - Write permission requires a signed JSON POST body containing a signature and a nonce.
    
    - Read permission requires either write permission, or an encrypted cookie that was created via the
      login challenge / response process. Read permission is intended to allow a user to read back his 
      own blinded information that has not yet been unblinded, for example to allow the browser to 
      immediately display recently submitted votes and posts.
    
    TODO: Resolve user's multiple keys into single master key or user_id?
    """
            
    def decorator(func):
        
        def proxyfunc(self, *args, **kw):
            
            import bitcoin as b

            self._current_user = {}
            
            #
            ## Get read authorization via encrypted cookies.
            ## Only for reading pending your own pending blind data:
            #

            if not needs_write: ## Don't bother checking for read if write is needed.
                
                cook = self.get_secure_cookie('auth')
                
                if cook:
                    h2 = json.loads(cook)
                    if (time() - h2['created'] <= cookie_expiration_time):
                        self._current_user = {'pub':h2['pub'],
                                              'has_read': True,
                                              'has_write': False,
                                              }
            
            #   
            ## Write authorization, must have valid monotonically increasing nonce:
            #
            
            try:
                hh = json.loads(self.request.body)
            except:
                hh = False
            
            if hh:
                print ('AUTH_CHECK_USER', hh['pub'][:32])

                hh['payload_decoded'] = json.loads(hh['payload'])
                
                if (hh['pub'] in LATEST_NONCE) and ('nonce' in hh['payload_decoded'])and (hh['payload_decoded']['nonce'] <= LATEST_NONCE[hh['pub']]):
                    print ('OUTDATED NONCE')
                    self.write_json({'error':'AUTH_OUTDATED_NONCE'})
                    return
                
                #LATEST_NONCE[user_key] = hh['payload_decoded']['nonce']
                
                is_success = b.ecdsa_raw_verify(b.sha256(hh['payload'].encode('utf8')),
                                                (hh['sig']['sig_v'],
                                                 b.decode(hh['sig']['sig_r'],16),
                                                 b.decode(hh['sig']['sig_s'],16),
                                                ),
                                                hh['pub'],
                                                )
                
                if is_success:
                    ## write auth overwrites read auth:
                    self._current_user = {'pub':hh['pub'],
                                          'has_read': True,
                                          'has_write': True,
                                          'write_data': hh,
                                          }
            
            if needs_read and not self._current_user.get('has_read'):
                print ('AUTH_FAILED_READ')
                self.write_json({'error':'AUTH_FAILED_READ'})
                #raise tornado.web.HTTPError(403)
                return
            
            if needs_write and not self._current_user.get('has_write'):
                print ('AUTH_FAILED_READ')
                self.write_json({'error':'AUTH_FAILED_READ'})
                #raise tornado.web.HTTPError(403)
                return
            
            ## TODO: per-public-key sponsorship rate throttling:
            
            self.add_header('X-RATE-USED','0')
            self.add_header('X-RATE-REMAINING','100')
            
            print ('AUTH_FINISHED', self._current_user)
            
            func(self, *args, **kw)
            
            return
        return proxyfunc
    return decorator

check_auth = check_auth_asymmetric


############## Web core:


class Application(tornado.web.Application):
    def __init__(self,
                 ):
        
        handlers = [(r'/',handle_front,),
                    (r'/demo',handle_front,),
                    (r'/login_1',handle_login_1,),
                    (r'/login_2',handle_login_2,),
                    (r'/blind',handle_blind,),
                    (r'/unblind',handle_unblind,),
                    (r'/submit',handle_submit_item,),
                    (r'/create_account',handle_create_account,),
                    (r'/track',handle_track,),
                    (r'/api',handle_api,),
                    (r'/echo',handle_echo,),
                    #(r'.*', handle_notfound,),
                    ]
        
        settings = {'template_path':join(dirname(__file__), 'templates_cccoin'),
                    'static_path':join(dirname(__file__), 'static_cccoin'),
                    'xsrf_cookies':False,
                    'cookie_secret':'1234',
                    }
        
        tornado.web.Application.__init__(self, handlers, **settings)


class BaseHandler(tornado.web.RequestHandler):
    
    def __init__(self, application, request, **kwargs):
        RequestHandler.__init__(self, application, request, **kwargs)
        
        self._current_user_read = False
        self._current_user_write = False
        
        self.loader = tornado.template.Loader('templates_cccoin/')

        #self.auth_state = False
        
    @property
    def io_loop(self,
                ):
        if not hasattr(self.application,'io_loop'):
            self.application.io_loop = IOLoop.instance()
        return self.application.io_loop
        
    def get_current_user(self,):
        return self._current_user
    
    @property
    def auth_state(self):
        if not self.application.auth_state:
            self.application.auth_state = AuthState()
        return self.application.auth_state

    @property
    def cccoin(self,
               ):
        if not hasattr(self.application,'cccoin'):
            self.application.cccoin = CCCoinAPI(mode = 'web')
        return self.application.cccoin
        
    @tornado.gen.engine
    def render_template(self,template_name, kwargs):
        """
        Central point to customize what variables get passed to templates.        
        """
        
        t0 = time()
        
        if 'self' in kwargs:
            kwargs['handler'] = kwargs['self']
            del kwargs['self']
        else:
            kwargs['handler'] = self

        from random import choice, randint
        kwargs['choice'] = choice
        kwargs['randint'] = randint
        kwargs['the_db'] = the_db
            
        r = self.loader.load(template_name).generate(**kwargs)
        
        print ('TEMPLATE TIME',(time()-t0)*1000)
        
        self.write(r)
        self.finish()
    
    def render_template_s(self,template_s,kwargs):
        """
        Render template from string.
        """
        
        t=Template(template_s)
        r=t.generate(**kwargs)
        self.write(r)
        self.finish()
        
    def write_json(self,
                   hh,
                   sort_keys = True,
                   indent = 4, #Set to None to do without newlines.
                   ):
        """
        Central point where we can customize the JSON output.
        """

        print ('WRITE_JSON',hh)
        
        if 'error' in hh:
            print ('ERROR',hh)
        
        self.set_header("Content-Type", "application/json")

        if False:
            zz = json.dumps(hh,
                            sort_keys = sort_keys,
                            indent = 4,
                            ) + '\n'
        else:
            zz = json.dumps(hh, sort_keys = True)

        print ('SENDING', zz)
            
        self.write(zz)
                       
        self.finish()
        

    def write_error(self,
                    status_code,
                    **kw):

        import traceback, sys, os
        ee = '\n'.join([line for line in traceback.format_exception(*sys.exc_info())])
        print (ee)
        self.write_json({'error':'INTERNAL_EXCEPTION','message':ee})

    
class handle_front(BaseHandler):
    @check_auth()
    @tornado.gen.coroutine
    def get(self):

        session = self.get_current_user()
        
        self.render_template('offchain_frontend.html',locals())

        if session:
            print ('MY_PUB', session['pub'])
        
        """
        as_html = intget(self.get_argument('html','0'), 0)
        offset = intget(self.get_argument('offset','0'), 0)
        increment = intget(self.get_argument('increment','50'), 50) or 50
        sort_by = self.get_argument('sort','score')
        
        items = self.cccoin.get_items(offset = offset,
                                      increment = increment,
                                      sort_by = sort_by,
                                      )

        print ('ITEMS', items)
        
        self.write_json(items)
        """

class handle_login_1(BaseHandler):
    #@check_auth(auth = False)
    @tornado.gen.coroutine
    def post(self):

        hh = json.loads(self.request.body)

        the_pub = hh['the_pub']
        
        challenge = CHALLENGES_DB.get(the_pub, False)
        
        if challenge is False:
            challenge = binascii.hexlify(urandom(16))
            CHALLENGES_DB[the_pub] = challenge

        self.write_json({'challenge':challenge})

import binascii
import bitcoin

class handle_login_2(BaseHandler):
    #@check_auth(auth = False)
    @tornado.gen.coroutine
    def post(self):

        hh = json.loads(self.request.body)
        
        """
        {the_pub: the_pub,
	 challenge: dd,
	 sig_v: sig.v,
	 sig_r: sig.r.toString('hex'),
	 sig_s: sig.s.toString('hex')
	}
        """
        
        the_pub = hh['the_pub']
        
        challenge = CHALLENGES_DB.get(the_pub, False)
        
        if challenge is False:
            print ('LOGIN_2: ERROR UNKNOWN CHALLENGE', challenge)
            self.write_json({'success':False,
                             'error':'UNKNOWN_OR_EXPIRED_CHALLENGE',
                             })
            return
        
        import bitcoin as b

        print 'GOT=============='
        print json.dumps(hh, indent=4)
        print '================='
        
        is_success = b.ecdsa_raw_verify(b.sha256(challenge.encode('utf8')),
                                        (hh['sig']['sig_v'],
                                         b.decode(hh['sig']['sig_r'],16),
                                         b.decode(hh['sig']['sig_s'],16)),
                                        the_pub,
                                        )
        
        print ('LOGIN_2_RESULT is_success:', is_success)
        
        self.set_secure_cookie('auth', json.dumps({'created':int(time()),
                                                   'pub':the_pub,
                                                   }))

        is_new = SEEN_USERS_DB.get(the_pub, False)
        SEEN_USERS_DB[the_pub] = True
        
        self.write_json({'success':is_success,
                         'is_new':is_new,
                         })
        


        
class handle_create_account(BaseHandler):
    
    @check_auth(needs_read = False, needs_write = False)
    @tornado.gen.coroutine
    def post(self):
        """
        """
        
        print ('CREATE_ACCOUNT')

        hh = json.loads(self.request.body)
        
        user_data = hh.get('user_data',{})

        password = hh.get('password','')
        
        if not password:
            self.write_json({'error':'BAD_PASSWORD'})
            return
        
        user = self.cccoin.create_account(user_data,
                                          password,
                                          ) 

        print ('CREATE_ACCOUNT_RETURNING', user)
        
        self.write_json(user)


class handle_submit_item(BaseHandler):

    @check_auth(needs_write = True)
    @tornado.gen.coroutine
    def post(self):

        print ('INSIDE handle_submit_item')
        
        user = self.get_current_user()
        
        data = self.request.body
        
        ## TODO: use callback to track confirmations?:
        
        tracking_id = RUN_ID + '|' + str(TRACKING_NUM.increment())

        sig = dict(self.request.headers).get("Sig", False)

        try:
            rr = self.cccoin.post_item(user['public_key'],
                                       data,
                                       sig,
                                       )
        except:
            import traceback, sys, os
            print '\n'.join([line for line in traceback.format_exception(*sys.exc_info())])

        print ('DONE_SUBMIT', rr)
        
        self.write_json(rr)


class handle_echo(BaseHandler):
    #@check_auth()
    @tornado.gen.coroutine
    def post(self):
        data = self.request.body
        print ('ECHO:')
        print (json.dumps(json.loads(data), indent=4))
        print
        self.write('{"success":true}')


from tornado.httpclient import AsyncHTTPClient

class handle_api(BaseHandler):

    #@check_auth()
    @tornado.gen.coroutine
    def post(self):

        data = self.request.body
        
        hh = json.loads(data)
        
        print ('THE_BODY', data)
                
        forward_url = 'http://127.0.0.1:50000/' + hh['command']

        print ('API_FORWARD', forward_url)
        
        response = yield AsyncHTTPClient().fetch(forward_url,
                                                 method = 'POST',
                                                 connect_timeout = 30,
                                                 request_timeout = 30,
                                                 body = data,
                                                 headers = dict(self.request.headers),
                                                 #allow_nonstandard_methods = True,
                                                 )
        d2 = response.body

        print ('D2', d2)
        
        self.write(d2)
        self.finish()
        

class handle_blind(BaseHandler):
    @check_auth(needs_write = True)
    @tornado.gen.coroutine
    def post(self):
        session = self.get_current_user()
        rr = self.cccoin.submit_blind_action(session['write_data'])
        self.write_json(rr)


class handle_unblind(BaseHandler):
    @check_auth(needs_write = True)
    @tornado.gen.coroutine
    def post(self):
        session = self.get_current_user()
        rr = self.cccoin.submit_unblind_action(session['write_data'])        
        self.write_json(rr)


        
class handle_track(BaseHandler):

    @check_auth()
    @tornado.gen.coroutine
    def post(self):
        
        tracking_id = intget(self.get_argument('tracking_id',''), False)
        
        self.write_json({'success':True, 'tracking_id':tracking_id, 'status':False})
        

def web(port = 50000,
        via_cli = False,
        ):
    """
    Web mode: Web server = Yes, Write rewards = No, Audit rewards = No.

    This mode runs a web server that users can access. Currently, writing of posts, votes and signups to the blockchain
    from this mode is allowed. Writing of rewards is disabled from this mode, so that you can run many instances of the web server
    without conflict.
    """
    
    print ('BINDING',port)
    
    try:
        tornado.options.parse_command_line()
        http_server = HTTPServer(Application(),
                                 xheaders=True,
                                 )
        http_server.bind(port)
        http_server.start(16) # Forks multiple sub-processes
        tornado.ioloop.IOLoop.instance().set_blocking_log_threshold(0.5)
        IOLoop.instance().start()
        
    except KeyboardInterrupt:
        print 'Exit'
    
    print ('WEB_STARTED')


def witness():
    """
    Witness mode: Web server = No, Write rewards = Yes, Audit rewards = No.
    
    Only run 1 instance of this witness, per community (contract instantiation.)
    
    This mode collects up events and distributes rewards on the blockchain. Currently, you must be the be owner of 
    the ethereum contract (you called `deploy_contract`) in order to distribute rewards.
    """
    
    xx = CCCoinAPI(mode = 'witness')
    
    while True:
        xx.loop_once()
        sleep(0.5)

def audit():
    """
    Audit mode: Web server = No, Write rewards = No, Audit rewards = Yes.
    """
    xx = CCCoinAPI(mode = 'audit')
    
    while True:
        xx.loop_once()
        sleep(0.5)

        
functions=['deploy_contract',
           'witness',
           'audit',
           'web',
           'sig_helper',
           'vote_helper',
           ]

def main():    
    setup_main(functions,
               globals(),
               'offchain.py',
               )

if __name__ == '__main__':
    main()

